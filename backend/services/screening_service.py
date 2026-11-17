"""Screening and controlled unit release service."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.auth import log_audit
from backend.models import BloodUnit, InventoryTransaction, ScreeningRecord
from backend.schemas import ScreeningDecision
from backend.validators.integrity import DomainValidationError, validate_inventory_transition


def record_screening_decision(
    session: Session,
    decision: ScreeningDecision,
    actor: str = "admin",
) -> ScreeningRecord:
    """Apply a screening review decision and transition unit inventory status safely."""
    unit = session.get(BloodUnit, decision.unit_id)
    if not unit:
        raise DomainValidationError(f"Blood unit ID {decision.unit_id} not found.")

    if unit.inventory_status == "Rejected" and decision.target_inventory_status == "Released":
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' is Rejected and can never be transitioned to Released."
        )
    if unit.inventory_status in ("Issued", "Discarded", "Expired"):
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' is in terminal/non-screenable status '{unit.inventory_status}'."
        )

    if decision.target_inventory_status == "Released":
        if decision.new_screening_status != "Cleared":
            raise DomainValidationError(
                "A unit may enter 'Released' status only when screening status is 'Cleared'."
            )
        if unit.expiry_date < date.today():
            raise DomainValidationError(
                f"Unit '{unit.unit_reference}' expired on {unit.expiry_date} and cannot be released."
            )

    old_status = unit.inventory_status
    validate_inventory_transition(old_status, decision.target_inventory_status)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    unit.screening_status = decision.new_screening_status
    unit.inventory_status = decision.target_inventory_status

    existing_count = session.query(ScreeningRecord).filter(ScreeningRecord.unit_id == unit.id).count()
    scr_ref = f"SCR-{unit.unit_reference}-R{existing_count + 1}"
    record = ScreeningRecord(
        screening_reference=scr_ref,
        unit_id=unit.id,
        screening_status=decision.new_screening_status,
        screening_date=date.today(),
        result_reference=decision.result_reference.strip(),
        reviewed_by=decision.reviewed_by.strip(),
        reviewed_at=now_utc,
        reference_note=decision.reference_note.strip(),
    )
    session.add(record)

    tx_map = {
        "Released": "RELEASED",
        "Quarantined": "QUARANTINED",
        "Rejected": "REJECTED",
        "Testing Pending": "SCREENING_PENDING",
    }
    session.add(
        InventoryTransaction(
            unit_id=unit.id,
            transaction_type=tx_map.get(decision.target_inventory_status, "SCREENING_UPDATE"),
            previous_status=old_status,
            new_status=decision.target_inventory_status,
            reference_type="SCREENING",
            reference_id=scr_ref,
            quantity=1,
            reason=decision.reference_note or f"Screening decision: {decision.new_screening_status}",
            performed_by=actor,
        )
    )
    log_audit(
        session,
        action="SCREENING_DECISION",
        entity_type="blood_unit",
        entity_id=unit.unit_reference,
        details=(
            f"Screening '{decision.new_screening_status}', status {old_status} -> "
            f"{decision.target_inventory_status} (ref: {decision.result_reference})"
        ),
        actor_name=actor,
    )
    return record


def list_screening_queue_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
    include_completed: bool = False,
) -> pd.DataFrame:
    """List units awaiting screening/release review (or all screening history)."""
    stmt = (
        select(BloodUnit)
        .options(
            joinedload(BloodUnit.blood_group),
            joinedload(BloodUnit.component),
            joinedload(BloodUnit.screening_records),
        )
        .order_by(BloodUnit.collection_date.asc(), BloodUnit.unit_reference.asc())
    )
    if blood_bank_id:
        stmt = stmt.where(BloodUnit.blood_bank_id == blood_bank_id)
    if not include_completed:
        stmt = stmt.where(BloodUnit.inventory_status.in_(["Collected", "Testing Pending", "Quarantined"]))

    units = session.scalars(stmt).unique().all()
    today = date.today()
    rows = []
    for u in units:
        latest = sorted(u.screening_records, key=lambda r: r.id)[-1] if u.screening_records else None
        days_pending = (today - u.collection_date).days
        rows.append(
            {
                "unit_id": u.id,
                "unit_reference": u.unit_reference,
                "blood_group": u.blood_group.display_name,
                "component": u.component.component_name,
                "collection_date": u.collection_date,
                "expiry_date": u.expiry_date,
                "days_since_collection": days_pending,
                "screening_status": u.screening_status,
                "inventory_status": u.inventory_status,
                "latest_screening_ref": latest.screening_reference if latest else "",
                "result_reference": latest.result_reference if latest else "",
                "reviewed_by": latest.reviewed_by if latest else "",
                "reviewed_at": latest.reviewed_at if latest else None,
                "notes": latest.reference_note if latest else "",
            }
        )
    return pd.DataFrame(rows)
