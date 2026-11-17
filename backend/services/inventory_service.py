"""Unit-level blood inventory management and stock reconciliation service."""

from __future__ import annotations

from datetime import date
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.auth import log_audit
from backend.models import (
    BloodBank,
    BloodComponent,
    BloodGroup,
    BloodUnit,
    Donation,
    InventoryTransaction,
    ScreeningRecord,
)
from backend.schemas import BloodUnitCreate
from backend.validators.integrity import (
    DomainValidationError,
    get_blood_group_by_name,
    get_component_by_name,
    validate_inventory_transition,
)


def create_blood_unit(
    session: Session,
    payload: BloodUnitCreate,
    actor: str = "admin",
) -> BloodUnit:
    """Create a validated blood unit, initial screening record, and transaction log."""
    existing = session.scalar(
        select(BloodUnit).where(BloodUnit.unit_reference == payload.unit_reference.strip())
    )
    if existing:
        raise DomainValidationError(f"Duplicate unit ID '{payload.unit_reference}'. Unit IDs must be unique.")

    donation = session.scalar(
        select(Donation).where(Donation.donation_reference == payload.donation_reference.strip())
    )
    if not donation:
        raise DomainValidationError(
            f"Donation reference '{payload.donation_reference}' not found. Every unit must trace to a donation."
        )
    if donation.collection_status == "Rejected":
        raise DomainValidationError(
            f"Donation '{donation.donation_reference}' was rejected and cannot produce inventory units."
        )

    bg = get_blood_group_by_name(session, payload.blood_group)
    comp = get_component_by_name(session, payload.component_name)
    if not comp.enabled:
        raise DomainValidationError(f"Component '{comp.component_name}' is currently disabled in settings.")

    bank = session.get(BloodBank, payload.blood_bank_id)
    if not bank:
        raise DomainValidationError(f"Blood bank ID {payload.blood_bank_id} not found.")

    if payload.collection_date < donation.donation_date:
        raise DomainValidationError(
            f"Unit collection date ({payload.collection_date}) cannot precede donation date ({donation.donation_date})."
        )

    unit = BloodUnit(
        unit_reference=payload.unit_reference.strip(),
        donation_id=donation.id,
        blood_bank_id=bank.id,
        blood_group_id=bg.id,
        component_id=comp.id,
        collection_date=payload.collection_date,
        processing_date=payload.processing_date,
        expiry_date=payload.expiry_date,
        screening_status=payload.screening_status,
        inventory_status=payload.inventory_status,
        storage_location=payload.storage_location.strip(),
    )
    session.add(unit)
    session.flush()

    tx_type = "RELEASED" if unit.inventory_status == "Released" else "COLLECTED"
    session.add(
        InventoryTransaction(
            unit_id=unit.id,
            transaction_type=tx_type,
            previous_status=None,
            new_status=unit.inventory_status,
            reference_type="DONATION",
            reference_id=donation.donation_reference,
            quantity=1,
            reason=f"Unit registered from donation {donation.donation_reference}",
            performed_by=actor,
        )
    )

    scr_ref = f"SCR-{unit.unit_reference}"
    session.add(
        ScreeningRecord(
            screening_reference=scr_ref,
            unit_id=unit.id,
            screening_status=unit.screening_status,
            screening_date=payload.processing_date or payload.collection_date,
            result_reference="INIT-REF",
            reviewed_by=actor if unit.screening_status == "Cleared" else None,
            reference_note="Initial unit intake screening status.",
        )
    )

    log_audit(
        session,
        action="CREATE_BLOOD_UNIT",
        entity_type="blood_unit",
        entity_id=unit.unit_reference,
        details=f"{bg.display_name} {comp.component_name} ({unit.inventory_status}) at {unit.storage_location}",
        actor_name=actor,
    )
    return unit


def update_unit_status(
    session: Session,
    unit_id: int,
    new_status: str,
    actor: str = "admin",
    reason: str = "",
    reference_type: str = "MANUAL",
    reference_id: str = "",
    transaction_type: Optional[str] = None,
) -> BloodUnit:
    """Perform a state-machine-validated status update with transaction logging."""
    unit = session.get(BloodUnit, unit_id)
    if not unit:
        raise DomainValidationError(f"Blood unit ID {unit_id} not found.")

    old_status = unit.inventory_status
    validate_inventory_transition(old_status, new_status)

    if new_status == "Released" and unit.screening_status != "Cleared":
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' cannot be released without 'Cleared' screening status."
        )
    if new_status == "Released" and unit.expiry_date < date.today():
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' is expired ({unit.expiry_date}) and cannot be released."
        )

    unit.inventory_status = new_status
    tx_label = transaction_type or new_status.upper().replace(" ", "_")
    session.add(
        InventoryTransaction(
            unit_id=unit.id,
            transaction_type=tx_label,
            previous_status=old_status,
            new_status=new_status,
            reference_type=reference_type,
            reference_id=reference_id or unit.unit_reference,
            quantity=1,
            reason=reason or f"Status transitioned from {old_status} to {new_status}",
            performed_by=actor,
        )
    )
    log_audit(
        session,
        action="UPDATE_UNIT_STATUS",
        entity_type="blood_unit",
        entity_id=unit.unit_reference,
        details=f"{old_status} -> {new_status}. {reason}".strip(),
        actor_name=actor,
    )
    return unit


def list_inventory_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
    blood_groups: Optional[list[str]] = None,
    components: Optional[list[str]] = None,
    statuses: Optional[list[str]] = None,
    storage_location: Optional[str] = None,
    search_unit_id: Optional[str] = None,
    collection_start: Optional[date] = None,
    collection_end: Optional[date] = None,
    expiry_start: Optional[date] = None,
    expiry_end: Optional[date] = None,
    as_of: Optional[date] = None,
) -> pd.DataFrame:
    """Retrieve filtered unit-level inventory as a DataFrame."""
    today = as_of or date.today()
    stmt = (
        select(BloodUnit)
        .options(
            joinedload(BloodUnit.blood_group),
            joinedload(BloodUnit.component),
            joinedload(BloodUnit.blood_bank),
            joinedload(BloodUnit.donation),
        )
        .order_by(BloodUnit.expiry_date.asc(), BloodUnit.unit_reference.asc())
    )
    if blood_bank_id:
        stmt = stmt.where(BloodUnit.blood_bank_id == blood_bank_id)
    if collection_start:
        stmt = stmt.where(BloodUnit.collection_date >= collection_start)
    if collection_end:
        stmt = stmt.where(BloodUnit.collection_date <= collection_end)
    if expiry_start:
        stmt = stmt.where(BloodUnit.expiry_date >= expiry_start)
    if expiry_end:
        stmt = stmt.where(BloodUnit.expiry_date <= expiry_end)
    if storage_location and storage_location != "All":
        stmt = stmt.where(BloodUnit.storage_location == storage_location)
    if search_unit_id and search_unit_id.strip():
        stmt = stmt.where(BloodUnit.unit_reference.ilike(f"%{search_unit_id.strip()}%"))

    units = session.scalars(stmt).all()
    rows = []
    for u in units:
        bg_name = u.blood_group.display_name
        comp_name = u.component.component_name
        if blood_groups and bg_name not in blood_groups:
            continue
        if components and comp_name not in components:
            continue
        if statuses and u.inventory_status not in statuses:
            continue
        remaining_days = (u.expiry_date - today).days
        is_available = u.inventory_status == "Released" and u.expiry_date >= today
        rows.append(
            {
                "id": u.id,
                "unit_reference": u.unit_reference,
                "donation_reference": u.donation.donation_reference if u.donation else "",
                "blood_bank": u.blood_bank.bank_name if u.blood_bank else "",
                "blood_group": bg_name,
                "component": comp_name,
                "collection_date": u.collection_date,
                "processing_date": u.processing_date,
                "expiry_date": u.expiry_date,
                "screening_status": u.screening_status,
                "inventory_status": u.inventory_status,
                "storage_location": u.storage_location,
                "remaining_days": remaining_days,
                "is_eligible_available": is_available,
            }
        )
    return pd.DataFrame(rows)


def get_stock_reconciliation(
    session: Session,
    blood_bank_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> dict:
    """Compute exact unit-level inventory counts reconciled directly from blood_units."""
    today = as_of or date.today()
    stmt = select(BloodUnit)
    if blood_bank_id:
        stmt = stmt.where(BloodUnit.blood_bank_id == blood_bank_id)
    units = session.scalars(stmt).all()

    counts = {
        "total_collected": len(units),
        "collected_raw": 0,
        "testing_pending": 0,
        "quarantined": 0,
        "total_released": 0,
        "current_available": 0,
        "total_reserved": 0,
        "total_issued": 0,
        "total_expired": 0,
        "total_discarded": 0,
        "total_rejected": 0,
        "expired_still_marked_released": 0,
    }
    for u in units:
        st = u.inventory_status
        if st == "Collected":
            counts["collected_raw"] += 1
        elif st == "Testing Pending":
            counts["testing_pending"] += 1
        elif st == "Quarantined":
            counts["quarantined"] += 1
        elif st == "Released":
            counts["total_released"] += 1
            if u.expiry_date >= today:
                counts["current_available"] += 1
            else:
                counts["expired_still_marked_released"] += 1
        elif st == "Reserved":
            counts["total_reserved"] += 1
        elif st == "Issued":
            counts["total_issued"] += 1
        elif st == "Expired":
            counts["total_expired"] += 1
        elif st == "Discarded":
            counts["total_discarded"] += 1
        elif st == "Rejected":
            counts["total_rejected"] += 1

    return counts


def get_stock_by_group_and_component(
    session: Session,
    blood_bank_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> pd.DataFrame:
    """Return unit-level stock breakdown by blood group and component."""
    df = list_inventory_df(session, blood_bank_id=blood_bank_id, as_of=as_of)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "blood_group",
                "component",
                "available",
                "reserved",
                "pending_screening",
                "quarantined",
                "issued",
                "expired",
                "discarded",
                "total_units",
            ]
        )

    grouped = (
        df.groupby(["blood_group", "component"], as_index=False)
        .agg(
            available=("is_eligible_available", "sum"),
            reserved=("inventory_status", lambda s: (s == "Reserved").sum()),
            pending_screening=("inventory_status", lambda s: s.isin(["Collected", "Testing Pending"]).sum()),
            quarantined=("inventory_status", lambda s: (s == "Quarantined").sum()),
            issued=("inventory_status", lambda s: (s == "Issued").sum()),
            expired=("inventory_status", lambda s: (s == "Expired").sum()),
            discarded=("inventory_status", lambda s: (s == "Discarded").sum()),
            total_units=("id", "count"),
        )
        .sort_values(["blood_group", "component"])
    )
    grouped["available"] = grouped["available"].astype(int)
    return grouped
