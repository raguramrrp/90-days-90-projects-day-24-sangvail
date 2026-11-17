"""Nearest Storage Hub Locator, Surgery Pre-Reservation, Cold-Chain Transport & Service Billing."""

from __future__ import annotations

import io
import math
from datetime import date, datetime, timezone
from typing import Optional
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import APP_NAME
from backend.auth import log_audit
from backend.models import (
    BloodAllocation,
    BloodBank,
    BloodComponent,
    BloodRequest,
    BloodUnit,
    Hospital,
    InventoryTransaction,
    ServicePayment,
    SurgicalBooking,
    TransportDispatch,
)
from backend.schemas import BloodRequestCreate
from backend.services.allocation_service import confirm_fefo_allocation
from backend.services.request_service import approve_request, cancel_request, create_blood_request, mark_request_issued
from backend.validators.integrity import (
    DomainValidationError,
    get_blood_group_by_name,
    get_component_by_name,
)

# Standardized Component Processing & Screening Service Fees (INR, NBTC-aligned service recovery model)
COMPONENT_PROCESSING_FEES: dict[str, float] = {
    "Red Blood Cells (RBC)": 1100.0,
    "Platelets": 400.0,
    "Fresh Frozen Plasma (FFP)": 400.0,
    "Whole Blood": 1100.0,
    "Cryoprecipitate": 250.0,
}

TRANSPORT_MODES: dict[str, dict] = {
    "Emergency Cold-Chain Ambulance": {"speed_kmh": 42.0, "base_fee": 650.0, "per_km": 35.0},
    "Validated Blood Courier Van": {"speed_kmh": 30.0, "base_fee": 350.0, "per_km": 22.0},
    "Hospital Dedicated Shuttle": {"speed_kmh": 26.0, "base_fee": 200.0, "per_km": 15.0},
}

SURGERY_PROCEDURES = [
    "Cardiac Bypass / Valve Surgery",
    "Orthopedic Joint Replacement",
    "Obstetric / Maternal Care Hold",
    "Oncology / Major Resection",
    "Trauma / Emergency Standby",
    "Organ / Hepatobiliary Procedure",
    "General Elective Surgery",
]

PAYMENT_METHODS = [
    "UPI Instant Settlement (Simulated)",
    "Hospital Credit Account",
    "Corporate Card Gateway (Simulated)",
    "NEFT / RTGS Transfer",
]

DISPATCH_FLOW = ["Scheduled", "Dispatched", "In Transit", "Delivered"]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in kilometers between two coordinates."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 2)


def find_nearest_storage_hubs(
    session: Session,
    blood_group: str,
    component_name: str,
    quantity_needed: int = 1,
    origin_lat: Optional[float] = None,
    origin_lon: Optional[float] = None,
    hospital_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> pd.DataFrame:
    """Rank all active blood bank storage hubs by distance with live eligible stock counts."""
    today = as_of or date.today()
    bg = get_blood_group_by_name(session, blood_group)
    comp = get_component_by_name(session, component_name)

    if hospital_id is not None:
        hosp = session.get(Hospital, hospital_id)
        if not hosp:
            raise DomainValidationError(f"Hospital ID {hospital_id} not found.")
        ref_lat, ref_lon = hosp.latitude, hosp.longitude
    else:
        ref_lat = origin_lat if origin_lat is not None else 13.0674
        ref_lon = origin_lon if origin_lon is not None else 80.2376

    banks = session.scalars(select(BloodBank).where(BloodBank.status == "Active").order_by(BloodBank.id)).all()
    active_reserved_ids = set(
        session.scalars(select(BloodAllocation.unit_id).where(BloodAllocation.allocation_status == "Reserved")).all()
    )

    rows = []
    for bank in banks:
        units = session.scalars(
            select(BloodUnit)
            .where(
                BloodUnit.blood_bank_id == bank.id,
                BloodUnit.blood_group_id == bg.id,
                BloodUnit.component_id == comp.id,
                BloodUnit.inventory_status == "Released",
                BloodUnit.screening_status == "Cleared",
                BloodUnit.expiry_date >= today,
            )
            .order_by(BloodUnit.expiry_date.asc())
        ).all()
        eligible = [u for u in units if u.id not in active_reserved_ids]
        dist_km = haversine_km(ref_lat, ref_lon, bank.latitude, bank.longitude)
        eta_min = max(8, int(round((dist_km / 30.0) * 60.0)) + 6)
        avail = len(eligible)
        earliest_exp = eligible[0].expiry_date if eligible else None
        rows.append(
            {
                "blood_bank_id": bank.id,
                "hub_name": bank.bank_name,
                "address": bank.address,
                "contact": bank.contact,
                "latitude": bank.latitude,
                "longitude": bank.longitude,
                "distance_km": dist_km,
                "est_transit_min": eta_min,
                "available_units": avail,
                "earliest_expiry": earliest_exp,
                "can_fulfill_full": avail >= quantity_needed,
                "availability_status": (
                    "Ready — Full Stock"
                    if avail >= quantity_needed
                    else ("Partial Stock" if avail > 0 else "Out of Stock")
                ),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            by=["can_fulfill_full", "distance_km", "available_units"],
            ascending=[False, True, False],
        ).reset_index(drop=True)
    return df


def request_and_reserve_from_hub(
    session: Session,
    hospital_id: int,
    blood_bank_id: int,
    blood_group: str,
    component_name: str,
    quantity: int,
    urgency: str = "Urgent",
    required_date: Optional[date] = None,
    auto_reserve: bool = True,
    human_approval_confirmed: bool = True,
    notes: str = "",
    actor: str = "admin",
) -> dict:
    """Create a hospital request against a specific nearest hub and optionally reserve FEFO units atomically."""
    today = date.today()
    need_dt = required_date or today
    ts_code = datetime.now(timezone.utc).strftime("%H%M%S%f")[:10]
    req_ref = f"REQ-NET-{ts_code}"

    req = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference=req_ref,
            blood_bank_id=blood_bank_id,
            hospital_id=hospital_id,
            blood_group=blood_group,
            component_name=component_name,
            required_quantity=quantity,
            urgency=urgency,
            request_date=today,
            required_date=need_dt,
            notes=notes or "Nearest-hub rapid stock request.",
        ),
        actor=actor,
    )
    session.flush()

    alloc_result = None
    if auto_reserve:
        approve_request(session, req.id, actor=actor, note="Approved for nearest-hub dispatch")
        session.flush()
        alloc_result = confirm_fefo_allocation(
            session,
            request_id=req.id,
            actor=actor,
            quantity=quantity,
            human_approval_confirmed=human_approval_confirmed,
        )

    return {
        "request_id": req.id,
        "request_reference": req.request_reference,
        "status": req.status,
        "allocated_count": alloc_result["allocated_count"] if alloc_result else 0,
        "allocated_units": alloc_result["allocated_units"] if alloc_result else [],
        "unfulfilled_quantity": max(0, req.required_quantity - req.fulfilled_quantity),
    }


# ---------------------------------------------------------------------------
# Surgery Pre-Reservation (Advance Booking)
# ---------------------------------------------------------------------------


def create_surgical_booking(
    session: Session,
    hospital_id: int,
    blood_bank_id: int,
    blood_group: str,
    component_name: str,
    quantity: int,
    procedure_category: str,
    surgery_date: date,
    hold_until_date: Optional[date] = None,
    human_approval_confirmed: bool = True,
    notes: str = "",
    actor: str = "admin",
    as_of: Optional[date] = None,
) -> dict:
    """
    Pre-reserve FEFO units for a scheduled surgery, ensuring reserved units will NOT expire
    before the scheduled surgery_date.
    """
    today = as_of or date.today()
    if surgery_date < today:
        raise DomainValidationError("Surgery date cannot be in the past.")
    hold_dt = hold_until_date or surgery_date
    if hold_dt < surgery_date:
        raise DomainValidationError("Hold-until date cannot be earlier than surgery date.")
    if quantity <= 0:
        raise DomainValidationError("Booking quantity must be greater than zero.")
    if not human_approval_confirmed:
        raise DomainValidationError("Administrative compatibility confirmation is required for surgical booking.")

    bg = get_blood_group_by_name(session, blood_group)
    comp = get_component_by_name(session, component_name)
    hosp = session.get(Hospital, hospital_id)
    bank = session.get(BloodBank, blood_bank_id)
    if not hosp or not bank:
        raise DomainValidationError("Invalid hospital or blood bank selected.")

    # Select only eligible units whose expiry_date >= surgery_date (valid on operation day!)
    active_reserved_ids = set(
        session.scalars(select(BloodAllocation.unit_id).where(BloodAllocation.allocation_status == "Reserved")).all()
    )
    candidates = session.scalars(
        select(BloodUnit)
        .where(
            BloodUnit.blood_bank_id == bank.id,
            BloodUnit.blood_group_id == bg.id,
            BloodUnit.component_id == comp.id,
            BloodUnit.inventory_status == "Released",
            BloodUnit.screening_status == "Cleared",
            BloodUnit.expiry_date >= surgery_date,
        )
        .order_by(BloodUnit.expiry_date.asc(), BloodUnit.collection_date.asc(), BloodUnit.id.asc())
    ).all()
    eligible = [u for u in candidates if u.id not in active_reserved_ids]

    if len(eligible) < quantity:
        raise DomainValidationError(
            f"Only {len(eligible)} eligible {blood_group} {component_name} unit(s) at {bank.bank_name} "
            f"remain valid through surgery date {surgery_date.isoformat()} (requested {quantity})."
        )

    selected_units = eligible[:quantity]
    ts_code = datetime.now(timezone.utc).strftime("%H%M%S%f")[:10]
    req_ref = f"REQ-SURG-{ts_code}"
    book_ref = f"SURG-{ts_code}"

    req = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference=req_ref,
            blood_bank_id=bank.id,
            hospital_id=hosp.id,
            blood_group=blood_group,
            component_name=component_name,
            required_quantity=quantity,
            urgency="Priority",
            request_date=today,
            required_date=surgery_date,
            notes=f"Surgical pre-reservation ({procedure_category}) for {surgery_date.isoformat()}. {notes}".strip(),
        ),
        actor=actor,
    )
    session.flush()
    approve_request(session, req.id, actor=actor, note=f"Approved for surgery booking {book_ref}")
    session.flush()

    alloc_res = confirm_fefo_allocation(
        session,
        request_id=req.id,
        actor=actor,
        unit_ids=[u.id for u in selected_units],
        human_approval_confirmed=True,
        as_of=today,
    )

    booking = SurgicalBooking(
        booking_reference=book_ref,
        request_id=req.id,
        hospital_id=hosp.id,
        blood_bank_id=bank.id,
        blood_group_id=bg.id,
        component_id=comp.id,
        procedure_category=procedure_category,
        surgery_date=surgery_date,
        hold_until_date=hold_dt,
        quantity=quantity,
        status="Reserved",
        notes=notes.strip(),
        created_by=actor,
    )
    session.add(booking)
    session.flush()

    log_audit(
        session,
        action="CREATE_SURGICAL_BOOKING",
        entity_type="surgical_booking",
        entity_id=book_ref,
        details=f"{hosp.hospital_name} | {procedure_category} on {surgery_date} | Units: {', '.join(alloc_res['allocated_units'])}",
        actor_name=actor,
    )
    return {
        "booking_id": booking.id,
        "booking_reference": book_ref,
        "request_id": req.id,
        "request_reference": req_ref,
        "reserved_units": alloc_res["allocated_units"],
        "surgery_date": surgery_date,
    }


def cancel_surgical_booking(session: Session, booking_id: int, reason: str, actor: str = "admin") -> SurgicalBooking:
    """Release a surgical pre-reservation hold and return units to eligible stock."""
    booking = session.get(SurgicalBooking, booking_id)
    if not booking:
        raise DomainValidationError(f"Surgical booking ID {booking_id} not found.")
    if booking.status != "Reserved":
        raise DomainValidationError(f"Only active 'Reserved' bookings can be cancelled (status: {booking.status}).")

    cancel_request(session, booking.request_id, reason or "Surgery cancelled / postponed", actor=actor)
    booking.status = "Cancelled"
    booking.notes = f"{booking.notes} | Cancelled: {reason}".strip(" |")
    session.flush()
    log_audit(
        session,
        action="CANCEL_SURGICAL_BOOKING",
        entity_type="surgical_booking",
        entity_id=booking.booking_reference,
        details=f"Hold released. Reason: {reason}",
        actor_name=actor,
    )
    return booking


def complete_surgical_booking(session: Session, booking_id: int, handover_note: str, actor: str = "admin") -> SurgicalBooking:
    """Issue pre-reserved units to the hospital surgical unit."""
    booking = session.get(SurgicalBooking, booking_id)
    if not booking:
        raise DomainValidationError(f"Surgical booking ID {booking_id} not found.")
    if booking.status != "Reserved":
        raise DomainValidationError(f"Only 'Reserved' bookings can be issued (status: {booking.status}).")

    mark_request_issued(session, booking.request_id, actor=actor, handover_note=handover_note or f"Issued for {booking.booking_reference}")
    booking.status = "Issued"
    session.flush()
    log_audit(
        session,
        action="ISSUE_SURGICAL_BOOKING",
        entity_type="surgical_booking",
        entity_id=booking.booking_reference,
        details=f"Units issued for {booking.procedure_category}.",
        actor_name=actor,
    )
    return booking


def list_surgical_bookings_df(session: Session, blood_bank_id: Optional[int] = None) -> pd.DataFrame:
    stmt = (
        select(SurgicalBooking)
        .options(
            joinedload(SurgicalBooking.hospital),
            joinedload(SurgicalBooking.blood_bank),
            joinedload(SurgicalBooking.blood_group),
            joinedload(SurgicalBooking.component),
            joinedload(SurgicalBooking.request),
        )
        .order_by(SurgicalBooking.surgery_date.asc(), SurgicalBooking.id.desc())
    )
    if blood_bank_id:
        stmt = stmt.where(SurgicalBooking.blood_bank_id == blood_bank_id)

    rows = []
    for b in session.scalars(stmt).all():
        rows.append(
            {
                "id": b.id,
                "booking_reference": b.booking_reference,
                "request_reference": b.request.request_reference,
                "hospital": b.hospital.hospital_name,
                "storage_hub": b.blood_bank.bank_name,
                "blood_group": b.blood_group.display_name,
                "component": b.component.component_name,
                "quantity": b.quantity,
                "procedure_category": b.procedure_category,
                "surgery_date": b.surgery_date,
                "hold_until_date": b.hold_until_date,
                "status": b.status,
                "notes": b.notes,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Cold-Chain Transport Arrangement & Dispatch Tracking
# ---------------------------------------------------------------------------


def arrange_transport_dispatch(
    session: Session,
    request_id: int,
    transport_mode: str,
    vehicle_reference: str,
    courier_name: str,
    container_id: str,
    notes: str = "",
    actor: str = "admin",
) -> TransportDispatch:
    """Schedule a validated cold-chain transport dispatch for an allocated or issued request."""
    if transport_mode not in TRANSPORT_MODES:
        raise DomainValidationError(f"Unsupported transport mode '{transport_mode}'.")
    req = session.scalar(
        select(BloodRequest)
        .options(
            joinedload(BloodRequest.blood_bank),
            joinedload(BloodRequest.hospital),
            joinedload(BloodRequest.component),
        )
        .where(BloodRequest.id == request_id)
    )
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")
    if req.status not in ("Partially Allocated", "Fully Allocated", "Issued"):
        raise DomainValidationError(
            f"Request '{req.request_reference}' must have allocated units before arranging transport (status: {req.status})."
        )

    dist_km = haversine_km(
        req.blood_bank.latitude, req.blood_bank.longitude,
        req.hospital.latitude, req.hospital.longitude,
    )
    speed = TRANSPORT_MODES[transport_mode]["speed_kmh"]
    eta_min = max(8, int(round((dist_km / speed) * 60.0)) + 5)

    ts_code = datetime.now(timezone.utc).strftime("%H%M%S%f")[:10]
    disp_ref = f"DSP-{ts_code}"

    dispatch = TransportDispatch(
        dispatch_reference=disp_ref,
        request_id=req.id,
        blood_bank_id=req.blood_bank_id,
        hospital_id=req.hospital_id,
        transport_mode=transport_mode,
        vehicle_reference=vehicle_reference.strip(),
        courier_name=courier_name.strip(),
        container_id=container_id.strip(),
        required_temp_range=req.component.storage_temp_range,
        distance_km=dist_km,
        eta_minutes=eta_min,
        status="Scheduled",
        notes=notes.strip(),
        created_by=actor,
    )
    session.add(dispatch)
    session.flush()
    log_audit(
        session,
        action="ARRANGE_TRANSPORT",
        entity_type="transport_dispatch",
        entity_id=disp_ref,
        details=f"{transport_mode} ({vehicle_reference}) | {req.blood_bank.bank_name} -> {req.hospital.hospital_name} ({dist_km} km, ETA {eta_min}m)",
        actor_name=actor,
    )
    return dispatch


def advance_dispatch_status(
    session: Session,
    dispatch_id: int,
    new_status: str,
    actor: str = "admin",
) -> TransportDispatch:
    """Advance dispatch lifecycle (Scheduled -> Dispatched -> In Transit -> Delivered)."""
    if new_status not in DISPATCH_FLOW:
        raise DomainValidationError(f"Invalid dispatch status '{new_status}'.")
    disp = session.get(TransportDispatch, dispatch_id)
    if not disp:
        raise DomainValidationError(f"Dispatch ID {dispatch_id} not found.")
    old_idx = DISPATCH_FLOW.index(disp.status)
    new_idx = DISPATCH_FLOW.index(new_status)
    if new_idx < old_idx:
        raise DomainValidationError(f"Cannot move dispatch backwards from '{disp.status}' to '{new_status}'.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = disp.status
    disp.status = new_status
    if new_status in ("Dispatched", "In Transit") and disp.dispatched_at is None:
        disp.dispatched_at = now
    if new_status == "Delivered":
        if disp.dispatched_at is None:
            disp.dispatched_at = now
        disp.delivered_at = now
        # If request is still Allocated, mark handover issued cleanly
        req = session.get(BloodRequest, disp.request_id)
        if req and req.status in ("Partially Allocated", "Fully Allocated"):
            mark_request_issued(session, req.id, actor=actor, handover_note=f"Delivered via {disp.dispatch_reference}")

    session.flush()
    log_audit(
        session,
        action="UPDATE_DISPATCH_STATUS",
        entity_type="transport_dispatch",
        entity_id=disp.dispatch_reference,
        details=f"{old} -> {new_status}",
        actor_name=actor,
    )
    return disp


def list_dispatches_df(session: Session, blood_bank_id: Optional[int] = None) -> pd.DataFrame:
    stmt = (
        select(TransportDispatch)
        .options(
            joinedload(TransportDispatch.request),
            joinedload(TransportDispatch.blood_bank),
            joinedload(TransportDispatch.hospital),
        )
        .order_by(TransportDispatch.created_at.desc(), TransportDispatch.id.desc())
    )
    if blood_bank_id:
        stmt = stmt.where(TransportDispatch.blood_bank_id == blood_bank_id)

    rows = []
    for d in session.scalars(stmt).all():
        rows.append(
            {
                "id": d.id,
                "dispatch_reference": d.dispatch_reference,
                "request_reference": d.request.request_reference,
                "origin_hub": d.blood_bank.bank_name,
                "destination_hospital": d.hospital.hospital_name,
                "transport_mode": d.transport_mode,
                "vehicle_reference": d.vehicle_reference,
                "courier_name": d.courier_name,
                "container_id": d.container_id,
                "temp_spec": d.required_temp_range,
                "distance_km": d.distance_km,
                "eta_minutes": d.eta_minutes,
                "status": d.status,
                "dispatched_at": d.dispatched_at.strftime("%Y-%m-%d %H:%M") if d.dispatched_at else "",
                "delivered_at": d.delivered_at.strftime("%Y-%m-%d %H:%M") if d.delivered_at else "",
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Processing & Cold-Chain Service Fee Billing + Simulated Online Payments
# ---------------------------------------------------------------------------


def estimate_service_charges(
    session: Session,
    request_id: int,
    dispatch_id: Optional[int] = None,
) -> dict:
    """Compute itemized processing/screening service fees and cold-chain logistics fees."""
    req = session.scalar(
        select(BloodRequest)
        .options(joinedload(BloodRequest.component), joinedload(BloodRequest.hospital))
        .where(BloodRequest.id == request_id)
    )
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")

    billable_units = max(1, req.fulfilled_quantity if req.fulfilled_quantity > 0 else req.required_quantity)
    unit_fee = COMPONENT_PROCESSING_FEES.get(req.component.component_name, 500.0)
    comp_total = round(unit_fee * billable_units, 2)

    transport_total = 0.0
    transport_desc = "Self-pickup / No transport scheduled"
    if dispatch_id:
        disp = session.get(TransportDispatch, dispatch_id)
        if disp:
            meta = TRANSPORT_MODES.get(disp.transport_mode, {"base_fee": 350.0, "per_km": 20.0})
            transport_total = round(meta["base_fee"] + meta["per_km"] * disp.distance_km, 2)
            transport_desc = f"{disp.transport_mode} ({disp.distance_km:.1f} km)"

    return {
        "request_reference": req.request_reference,
        "hospital_name": req.hospital.hospital_name,
        "component_name": req.component.component_name,
        "billable_units": billable_units,
        "unit_processing_fee": unit_fee,
        "component_service_fee": comp_total,
        "transport_fee": transport_total,
        "transport_description": transport_desc,
        "total_amount": round(comp_total + transport_total, 2),
        "currency": "INR",
    }


def record_service_payment(
    session: Session,
    request_id: int,
    payment_method: str,
    dispatch_id: Optional[int] = None,
    notes: str = "",
    actor: str = "admin",
) -> ServicePayment:
    """Record a simulated online processing & logistics fee settlement with receipt ID."""
    if payment_method not in PAYMENT_METHODS:
        raise DomainValidationError(f"Unsupported payment method '{payment_method}'.")
    req = session.get(BloodRequest, request_id)
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")

    est = estimate_service_charges(session, request_id=request_id, dispatch_id=dispatch_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ts_code = now.strftime("%Y%m%d%H%M%S%f")[:16]
    pay_ref = f"PAY-{ts_code[-10:]}"
    tx_ref = f"TXN-SIM-{ts_code[-8:]}"
    status = "Billed to Account" if payment_method == "Hospital Credit Account" else "Paid"

    payment = ServicePayment(
        payment_reference=pay_ref,
        request_id=req.id,
        dispatch_id=dispatch_id,
        hospital_id=req.hospital_id,
        component_service_fee=est["component_service_fee"],
        transport_fee=est["transport_fee"],
        total_amount=est["total_amount"],
        currency="INR",
        payment_method=payment_method,
        payment_status=status,
        transaction_ref=tx_ref,
        paid_at=now if status == "Paid" else None,
        notes=notes.strip() or "Component processing, screening & cold-chain logistics service fee.",
        created_by=actor,
    )
    session.add(payment)
    session.flush()
    log_audit(
        session,
        action="RECORD_SERVICE_PAYMENT",
        entity_type="service_payment",
        entity_id=pay_ref,
        details=f"{payment_method} | INR {est['total_amount']:.2f} ({status}) for {req.request_reference}",
        actor_name=actor,
    )
    return payment


def list_payments_df(session: Session) -> pd.DataFrame:
    stmt = (
        select(ServicePayment)
        .options(
            joinedload(ServicePayment.request),
            joinedload(ServicePayment.hospital),
            joinedload(ServicePayment.dispatch),
        )
        .order_by(ServicePayment.created_at.desc(), ServicePayment.id.desc())
    )
    rows = []
    for p in session.scalars(stmt).all():
        rows.append(
            {
                "id": p.id,
                "payment_reference": p.payment_reference,
                "request_reference": p.request.request_reference,
                "dispatch_reference": p.dispatch.dispatch_reference if p.dispatch else "-",
                "hospital": p.hospital.hospital_name,
                "processing_fee": p.component_service_fee,
                "transport_fee": p.transport_fee,
                "total_amount": p.total_amount,
                "currency": p.currency,
                "payment_method": p.payment_method,
                "status": p.payment_status,
                "transaction_ref": p.transaction_ref,
                "timestamp": p.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )
    return pd.DataFrame(rows)


def _amount_in_words_inr(amount: float) -> str:
    """Convert numeric INR amount into formal invoice words (Indian/standard scale)."""
    whole = int(round(amount))
    if whole == 0:
        return "Rupees Zero Only"
    ones = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen",
    ]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def _two_digits(n: int) -> str:
        if n < 20:
            return ones[n]
        return f"{tens[n // 10]} {ones[n % 10]}".strip()

    def _three_digits(n: int) -> str:
        if n >= 100:
            rem = n % 100
            return f"{ones[n // 100]} Hundred" + (f" {_two_digits(rem)}" if rem else "")
        return _two_digits(n)

    parts = []
    lakhs = whole // 100000
    whole %= 100000
    thousands = whole // 1000
    whole %= 1000
    if lakhs:
        parts.append(f"{_two_digits(lakhs)} Lakh")
    if thousands:
        parts.append(f"{_two_digits(thousands)} Thousand")
    if whole:
        parts.append(_three_digits(whole))
    return f"Rupees {' '.join(parts)} Only"


def generate_payment_receipt_pdf(session: Session, payment_id: int) -> bytes:
    """Generate a realistic hospital-grade Processing & Cold-Chain Service Invoice PDF using ReportLab."""
    payment = session.scalar(
        select(ServicePayment)
        .options(
            joinedload(ServicePayment.request).joinedload(BloodRequest.blood_group),
            joinedload(ServicePayment.request).joinedload(BloodRequest.component),
            joinedload(ServicePayment.request).joinedload(BloodRequest.blood_bank),
            joinedload(ServicePayment.request).joinedload(BloodRequest.allocations).joinedload(BloodAllocation.unit),
            joinedload(ServicePayment.hospital),
            joinedload(ServicePayment.dispatch),
        )
        .where(ServicePayment.id == payment_id)
    )
    if not payment:
        raise DomainValidationError(f"Payment ID {payment_id} not found.")

    req = payment.request
    bank = req.blood_bank
    hosp = payment.hospital
    disp = payment.dispatch

    # Deterministic fictional invoice metadata for realistic formatting without real PHI
    fictional_patients = [
        ("Arjun K.", "IPD-2026-4812", "Dr. S. Meenakshi", "Cardiothoracic Ward 3B"),
        ("Priya N.", "IPD-2026-5104", "Dr. R. Karthikeyan", "Surgical ICU — Bed 08"),
        ("Vikram S.", "IPD-2026-5390", "Dr. A. Lakshmi", "Orthopedic Wing 2A"),
        ("Divya M.", "IPD-2026-5621", "Dr. K. Subramanian", "Maternal Care Suite 1C"),
    ]
    p_name, ipd_no, doc_name, ward_name = fictional_patients[payment.id % len(fictional_patients)]

    allocated_units = [
        a.unit.unit_reference
        for a in (req.allocations or [])
        if a.allocation_status in ("Reserved", "Issued") and a.unit is not None
    ]
    units_label = ", ".join(allocated_units[:6]) if allocated_units else f"Pending FEFO Assignment ({req.required_quantity}u)"
    billable_qty = max(1, req.fulfilled_quantity if req.fulfilled_quantity > 0 else req.required_quantity)

    # Split processing recovery transparently into Component Separation (~75%) + TTI/NAT Screening (~25%)
    comp_proc_fee = round(payment.component_service_fee * 0.75, 2)
    screening_fee = round(payment.component_service_fee - comp_proc_fee, 2)
    transport_fee = round(payment.transport_fee, 2)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    w_white_title = ParagraphStyle("InvWTitle", parent=styles["Heading1"], fontSize=16, textColor=colors.white, leading=19, spaceAfter=2)
    w_white_sub = ParagraphStyle("InvWSub", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#CCFBF1"), leading=12)
    w_right_hdr = ParagraphStyle("InvRHdr", parent=styles["Normal"], fontSize=9, textColor=colors.white, alignment=2, leading=13)
    lbl_bold = ParagraphStyle("InvLblB", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#0F172A"), leading=12.5)
    lbl_muted = ParagraphStyle("InvLblM", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#64748B"), leading=11.5)
    note_st = ParagraphStyle("InvNote", parent=styles["Normal"], fontSize=7.8, textColor=colors.HexColor("#64748B"), leading=11)

    # 1. Top Clinical Teal Banner Header
    banner_data = [[
        Paragraph(
            f"<b>{APP_NAME} BLOOD SERVICES</b><br/>"
            f"<font size='8.5' color='#CCFBF1'>{bank.bank_name} · {bank.address}</font><br/>"
            f"<font size='7.8' color='#99F6E4'>License No: BB-REG-2026-0412 &nbsp;|&nbsp; Contact: {bank.contact}</font>",
            w_white_title,
        ),
        Paragraph(
            f"<b>SERVICE COST-RECOVERY INVOICE</b><br/>"
            f"Invoice No: <b>{payment.payment_reference}</b><br/>"
            f"Date: {payment.created_at.strftime('%d-%b-%Y %H:%M UTC')}<br/>"
            f"Status: <b>{payment.payment_status.upper()}</b>",
            w_right_hdr,
        ),
    ]]
    t_banner = Table(banner_data, colWidths=[4.5 * inch, 2.9 * inch])
    t_banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0F3D3E")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )

    # 2. Two-Column Billing & Clinical Reference Block
    info_data = [[
        Paragraph(
            f"<font size='7.5' color='#64748B'><b>BILLED TO (HOSPITAL / REQUESTER)</b></font><br/>"
            f"<b>{hosp.hospital_name}</b><br/>"
            f"{hosp.address}<br/>"
            f"Contact: {hosp.contact}<br/>"
            f"Requester Account: {payment.created_by}",
            lbl_bold,
        ),
        Paragraph(
            f"<font size='7.5' color='#64748B'><b>CLINICAL CASE &amp; CUSTODY DETAILS</b></font><br/>"
            f"Patient Ref: <b>{p_name}</b> &nbsp;|&nbsp; Case ID: <b>{ipd_no}</b><br/>"
            f"Attending: {doc_name} ({ward_name})<br/>"
            f"Request ID: <b>{req.request_reference}</b> &nbsp;|&nbsp; Group: <b>{req.blood_group.display_name}</b><br/>"
            f"Unit Bag IDs: <b>{units_label}</b>",
            lbl_bold,
        ),
    ]]
    t_info = Table(info_data, colWidths=[3.55 * inch, 3.85 * inch])
    t_info.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#CBD5E1")),
                ("LINEBEFORE", (1, 0), (1, 0), 0.7, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )

    # 3. Detailed Itemized Service Cost-Recovery Table (Paragraph-wrapped descriptions, spanned totals)
    desc_st = ParagraphStyle("InvDesc", parent=styles["Normal"], fontSize=8.2, textColor=colors.HexColor("#0F172A"), leading=11.5)
    fee_rows = [
        ["#", "Service Description", "SAC Code", "Qty", "Rate (INR)", "GST", "Amount (INR)"],
        [
            "1",
            Paragraph(
                f"Component Preparation &amp; Cold-Storage Processing<br/>"
                f"<font size='7.6' color='#475569'>({req.component.component_name} · {req.blood_group.display_name})</font>",
                desc_st,
            ),
            "999311",
            str(billable_qty),
            f"{comp_proc_fee / billable_qty:,.2f}",
            "0% Exempt",
            f"{comp_proc_fee:,.2f}",
        ],
        [
            "2",
            Paragraph("Mandatory TTI Screening, Grouping &amp; Bag Consumables Recovery", desc_st),
            "999311",
            str(billable_qty),
            f"{screening_fee / billable_qty:,.2f}",
            "0% Exempt",
            f"{screening_fee:,.2f}",
        ],
    ]
    if transport_fee > 0 and disp is not None:
        fee_rows.append(
            [
                "3",
                Paragraph(
                    f"Cold-Chain Logistics — {disp.transport_mode}<br/>"
                    f"<font size='7.6' color='#475569'>(Container: {disp.container_id} · {disp.required_temp_range} · {disp.distance_km:.1f} km)</font>",
                    desc_st,
                ),
                "996511",
                "1",
                f"{transport_fee:,.2f}",
                "0% Exempt",
                f"{transport_fee:,.2f}",
            ]
        )
    else:
        fee_rows.append(
            [
                "3",
                Paragraph("Cold-Chain Transport (Hospital Self-Pickup / Direct Handover)", desc_st),
                "996511",
                "1",
                "0.00",
                "0% Exempt",
                "0.00",
            ]
        )

    fee_rows.append(["", "", "", "", "Subtotal", "", f"{payment.total_amount:,.2f}"])
    fee_rows.append(["", "", "", "", "Healthcare GST (0%)", "", "0.00"])
    fee_rows.append(["", "", "", "", "TOTAL PAYABLE", "", f"INR {payment.total_amount:,.2f}"])

    t_fee = Table(
        fee_rows,
        colWidths=[0.35 * inch, 3.10 * inch, 0.72 * inch, 0.43 * inch, 0.85 * inch, 0.85 * inch, 1.10 * inch],
        repeatRows=1,
    )
    n_items = len(fee_rows) - 3
    t_fee.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8.2),
                ("FONTSIZE", (0, 1), (-1, -1), 8.2),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#0F172A")),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (2, 0), (3, -1), "CENTER"),
                ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, n_items - 1), 0.4, colors.HexColor("#E2E8F0")),
                ("SPAN", (4, n_items), (5, n_items)),
                ("SPAN", (4, n_items + 1), (5, n_items + 1)),
                ("SPAN", (4, n_items + 2), (5, n_items + 2)),
                ("LINEABOVE", (4, n_items), (-1, n_items), 0.7, colors.HexColor("#CBD5E1")),
                ("FONTNAME", (4, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (4, -1), (-1, -1), colors.HexColor("#F0FDFA")),
                ("TEXTCOLOR", (4, -1), (-1, -1), colors.HexColor("#0F766E")),
                ("BOX", (4, -1), (-1, -1), 0.8, colors.HexColor("#0F766E")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    # 4. Amount in Words + Settlement & Signatory Footer
    words_str = _amount_in_words_inr(payment.total_amount)
    clean_method = payment.payment_method.replace(" (Simulated)", "")
    pay_details = [[
        Paragraph(
            f"<b>Amount in Words:</b> {words_str}<br/>"
            f"<b>Payment Mode:</b> {clean_method}<br/>"
            f"<b>Settlement / UTR Ref:</b> {payment.transaction_ref}<br/>"
            f"<b>Cold-Chain Dispatch Ref:</b> {disp.dispatch_reference if disp else 'Direct Counter Handover'}",
            lbl_bold,
        ),
        Paragraph(
            f"<font color='#065F46'><b>[{payment.payment_status.upper()}]</b></font><br/><br/>"
            f"_____________________________<br/>"
            f"<b>Authorized Blood Bank Officer</b><br/>"
            f"<font size='7.5' color='#64748B'>{bank.bank_name}</font>",
            ParagraphStyle("SigR", parent=lbl_bold, alignment=2),
        ),
    ]]
    t_pay = Table(pay_details, colWidths=[4.7 * inch, 2.7 * inch])
    t_pay.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )

    elements = [
        t_banner,
        Spacer(1, 12),
        t_info,
        Spacer(1, 14),
        t_fee,
        Spacer(1, 14),
        t_pay,
        Spacer(1, 12),
        Paragraph(
            "<b>Statutory &amp; Ethical Billing Notice:</b> Blood and blood components are never sold. "
            "Amounts billed reflect standardized processing, mandatory infectious-disease screening, blood bag consumables, "
            "and cold-chain logistics cost recovery only (Healthcare Services SAC 999311 — GST Exempt). "
            "Patient name, IPD case number, and license number shown above are fictional placeholder fields for system billing formatting.",
            note_st,
        ),
    ]
    doc.build(elements)
    return buf.getvalue()
