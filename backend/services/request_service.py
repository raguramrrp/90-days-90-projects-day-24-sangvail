"""Hospital blood request management workflow service."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.auth import log_audit
from backend.models import (
    BloodAllocation,
    BloodBank,
    BloodRequest,
    BloodUnit,
    Hospital,
    InventoryTransaction,
)
from backend.schemas import BloodRequestCreate
from backend.validators.integrity import (
    DomainValidationError,
    assert_unit_can_be_issued,
    get_blood_group_by_name,
    get_component_by_name,
    validate_request_transition,
)


def create_blood_request(
    session: Session,
    payload: BloodRequestCreate,
    actor: str = "admin",
) -> BloodRequest:
    """Create a validated hospital blood request."""
    existing = session.scalar(
        select(BloodRequest).where(BloodRequest.request_reference == payload.request_reference.strip())
    )
    if existing:
        raise DomainValidationError(f"Duplicate request reference '{payload.request_reference}'.")

    bank = session.get(BloodBank, payload.blood_bank_id)
    if not bank:
        raise DomainValidationError(f"Blood bank ID {payload.blood_bank_id} not found.")
    hospital = session.get(Hospital, payload.hospital_id)
    if not hospital:
        raise DomainValidationError(f"Hospital ID {payload.hospital_id} not found.")

    bg = get_blood_group_by_name(session, payload.blood_group)
    comp = get_component_by_name(session, payload.component_name)

    req = BloodRequest(
        request_reference=payload.request_reference.strip(),
        blood_bank_id=bank.id,
        hospital_id=hospital.id,
        blood_group_id=bg.id,
        component_id=comp.id,
        required_quantity=payload.required_quantity,
        fulfilled_quantity=0,
        urgency=payload.urgency,
        request_date=payload.request_date,
        required_date=payload.required_date,
        status="Submitted",
        notes=payload.notes.strip(),
        created_by=actor,
    )
    session.add(req)
    session.flush()
    log_audit(
        session,
        action="CREATE_BLOOD_REQUEST",
        entity_type="blood_request",
        entity_id=req.request_reference,
        details=f"{hospital.hospital_name}: {req.required_quantity}x {bg.display_name} {comp.component_name} ({req.urgency})",
        actor_name=actor,
    )
    return req


def approve_request(session: Session, request_id: int, actor: str = "admin", note: str = "") -> BloodRequest:
    """Approve a submitted or under-review blood request."""
    req = session.get(BloodRequest, request_id)
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")
    validate_request_transition(req.status, "Approved")
    old = req.status
    req.status = "Approved"
    if note:
        req.notes = f"{req.notes} | Approved: {note}".strip(" |")
    log_audit(
        session,
        action="APPROVE_REQUEST",
        entity_type="blood_request",
        entity_id=req.request_reference,
        details=f"{old} -> Approved. {note}".strip(),
        actor_name=actor,
    )
    return req


def reject_request(session: Session, request_id: int, reason: str, actor: str = "admin") -> BloodRequest:
    """Reject a request with a mandatory reason."""
    if not reason or not reason.strip():
        raise DomainValidationError("A rejection reason is required.")
    req = session.get(BloodRequest, request_id)
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")
    if req.fulfilled_quantity > 0:
        raise DomainValidationError(
            "Cannot reject a request that already has allocated units. Reverse active allocations first."
        )
    validate_request_transition(req.status, "Rejected")
    old = req.status
    req.status = "Rejected"
    req.notes = f"{req.notes} | Rejected: {reason.strip()}".strip(" |")
    log_audit(
        session,
        action="REJECT_REQUEST",
        entity_type="blood_request",
        entity_id=req.request_reference,
        details=f"{old} -> Rejected: {reason.strip()}",
        actor_name=actor,
    )
    return req


def cancel_request(session: Session, request_id: int, reason: str, actor: str = "admin") -> BloodRequest:
    """Cancel an unissued request, reversing any reserved allocations atomically."""
    req = session.scalar(
        select(BloodRequest)
        .options(joinedload(BloodRequest.allocations).joinedload(BloodAllocation.unit))
        .where(BloodRequest.id == request_id)
    )
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")
    if req.status in ("Issued", "Closed", "Cancelled", "Rejected"):
        raise DomainValidationError(f"Cannot cancel request in status '{req.status}'.")

    today = date.today()
    for alloc in req.allocations:
        if alloc.allocation_status == "Reserved":
            unit: BloodUnit = alloc.unit
            prev_status = unit.inventory_status
            restored = "Expired" if unit.expiry_date < today else "Released"
            unit.inventory_status = restored
            alloc.allocation_status = "Reversed"
            alloc.notes = f"{alloc.notes} | Reversed on request cancel".strip(" |")
            session.add(
                InventoryTransaction(
                    unit_id=unit.id,
                    transaction_type="ALLOCATION_REVERSED",
                    previous_status=prev_status,
                    new_status=restored,
                    reference_type="REQUEST",
                    reference_id=req.request_reference,
                    quantity=1,
                    reason=f"Request {req.request_reference} cancelled: {reason}",
                    performed_by=actor,
                )
            )
    req.fulfilled_quantity = 0
    old = req.status
    req.status = "Cancelled"
    req.notes = f"{req.notes} | Cancelled: {reason.strip()}".strip(" |")
    log_audit(
        session,
        action="CANCEL_REQUEST",
        entity_type="blood_request",
        entity_id=req.request_reference,
        details=f"{old} -> Cancelled: {reason.strip()}",
        actor_name=actor,
    )
    return req


def mark_request_issued(
    session: Session,
    request_id: int,
    actor: str = "admin",
    handover_note: str = "",
) -> BloodRequest:
    """Issue all currently reserved allocations for a request after authorized handover."""
    req = session.scalar(
        select(BloodRequest)
        .options(joinedload(BloodRequest.allocations).joinedload(BloodAllocation.unit))
        .where(BloodRequest.id == request_id)
    )
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")
    if req.status not in ("Partially Allocated", "Fully Allocated"):
        raise DomainValidationError(
            f"Only allocated requests can be marked Issued (current status: '{req.status}')."
        )

    reserved_allocs = [a for a in req.allocations if a.allocation_status == "Reserved"]
    if not reserved_allocs:
        raise DomainValidationError("No reserved allocations exist to issue for this request.")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    today = date.today()
    for alloc in reserved_allocs:
        unit = alloc.unit
        assert_unit_can_be_issued(unit, as_of=today)
        prev_status = unit.inventory_status
        unit.inventory_status = "Issued"
        alloc.allocation_status = "Issued"
        alloc.issue_date = now_utc
        session.add(
            InventoryTransaction(
                unit_id=unit.id,
                transaction_type="ISSUED",
                previous_status=prev_status,
                new_status="Issued",
                reference_type="REQUEST",
                reference_id=req.request_reference,
                quantity=1,
                reason=handover_note or f"Issued for request {req.request_reference}",
                performed_by=actor,
            )
        )

    req.status = "Issued"
    if handover_note:
        req.notes = f"{req.notes} | Handover: {handover_note}".strip(" |")
    log_audit(
        session,
        action="ISSUE_REQUEST",
        entity_type="blood_request",
        entity_id=req.request_reference,
        details=f"Issued {len(reserved_allocs)} reserved unit(s). {handover_note}".strip(),
        actor_name=actor,
    )
    return req


def list_requests_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
    blood_groups: Optional[list[str]] = None,
    components: Optional[list[str]] = None,
    statuses: Optional[list[str]] = None,
    urgencies: Optional[list[str]] = None,
    hospital_name: Optional[str] = None,
    search_ref: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    created_by: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch filtered hospital blood requests."""
    stmt = (
        select(BloodRequest)
        .options(
            joinedload(BloodRequest.hospital),
            joinedload(BloodRequest.blood_group),
            joinedload(BloodRequest.component),
        )
        .order_by(BloodRequest.request_date.desc(), BloodRequest.id.desc())
    )
    if blood_bank_id:
        stmt = stmt.where(BloodRequest.blood_bank_id == blood_bank_id)
    if start_date:
        stmt = stmt.where(BloodRequest.request_date >= start_date)
    if end_date:
        stmt = stmt.where(BloodRequest.request_date <= end_date)
    if search_ref and search_ref.strip():
        stmt = stmt.where(BloodRequest.request_reference.ilike(f"%{search_ref.strip()}%"))
    if created_by:
        stmt = stmt.where(BloodRequest.created_by == created_by)

    requests = session.scalars(stmt).all()
    rows = []
    for r in requests:
        bg = r.blood_group.display_name
        comp = r.component.component_name
        hosp = r.hospital.hospital_name
        if blood_groups and bg not in blood_groups:
            continue
        if components and comp not in components:
            continue
        if statuses and r.status not in statuses:
            continue
        if urgencies and r.urgency not in urgencies:
            continue
        if hospital_name and hospital_name != "All" and hosp != hospital_name:
            continue
        remaining = max(0, r.required_quantity - r.fulfilled_quantity)
        rows.append(
            {
                "id": r.id,
                "request_reference": r.request_reference,
                "hospital": hosp,
                "blood_group": bg,
                "component": comp,
                "required_quantity": r.required_quantity,
                "allocated_quantity": r.fulfilled_quantity,
                "remaining_quantity": remaining,
                "urgency": r.urgency,
                "request_date": r.request_date,
                "required_date": r.required_date,
                "status": r.status,
                "notes": r.notes,
            }
        )
    return pd.DataFrame(rows)


def list_allocations_for_request_df(session: Session, request_id: int) -> pd.DataFrame:
    """List allocation history for a specific request."""
    stmt = (
        select(BloodAllocation)
        .options(
            joinedload(BloodAllocation.unit).joinedload(BloodUnit.blood_group),
            joinedload(BloodAllocation.unit).joinedload(BloodUnit.component),
        )
        .where(BloodAllocation.request_id == request_id)
        .order_by(BloodAllocation.allocation_date.desc())
    )
    allocs = session.scalars(stmt).all()
    rows = []
    for a in allocs:
        rows.append(
            {
                "allocation_id": a.id,
                "unit_id": a.unit_id,
                "unit_reference": a.unit.unit_reference,
                "blood_group": a.unit.blood_group.display_name,
                "component": a.unit.component.component_name,
                "expiry_date": a.unit.expiry_date,
                "allocation_status": a.allocation_status,
                "unit_status": a.unit.inventory_status,
                "allocation_date": a.allocation_date,
                "issue_date": a.issue_date,
                "allocated_by": a.allocated_by,
                "notes": a.notes,
            }
        )
    return pd.DataFrame(rows)
