"""Expiry monitoring, configurable component windows, and controlled discard workflows."""

from __future__ import annotations

from datetime import date
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.auth import log_audit
from backend.models import BloodUnit, InventoryTransaction, StockThreshold
from backend.validators.integrity import DomainValidationError


def _build_threshold_lookup(session: Session, blood_bank_id: Optional[int] = None) -> dict[tuple[int, int, int], tuple[int, int]]:
    stmt = select(StockThreshold)
    if blood_bank_id:
        stmt = stmt.where(StockThreshold.blood_bank_id == blood_bank_id)
    thresholds = session.scalars(stmt).all()
    return {
        (t.blood_bank_id, t.blood_group_id, t.component_id): (t.warning_days, t.critical_days)
        for t in thresholds
    }


def classify_expiry_window(remaining_days: int, warning_days: int, critical_days: int) -> str:
    """Categorize a unit's remaining shelf life using component- and bank-specific policy."""
    if remaining_days < 0:
        return "Expired"
    if remaining_days <= critical_days:
        return "Critical Window"
    if remaining_days <= warning_days:
        return "Approaching Expiry"
    return "Normal Shelf Life"


def get_expiry_monitor_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
    as_of: Optional[date] = None,
    include_discarded: bool = False,
) -> pd.DataFrame:
    """Return active inventory annotated with configurable expiry risk windows."""
    today = as_of or date.today()
    thresholds = _build_threshold_lookup(session, blood_bank_id)

    statuses = ["Released", "Reserved", "Expired", "Testing Pending", "Quarantined"]
    if include_discarded:
        statuses.append("Discarded")

    stmt = (
        select(BloodUnit)
        .options(
            joinedload(BloodUnit.blood_group),
            joinedload(BloodUnit.component),
            joinedload(BloodUnit.blood_bank),
        )
        .where(BloodUnit.inventory_status.in_(statuses))
        .order_by(BloodUnit.expiry_date.asc(), BloodUnit.unit_reference.asc())
    )
    if blood_bank_id:
        stmt = stmt.where(BloodUnit.blood_bank_id == blood_bank_id)

    units = session.scalars(stmt).all()
    rows = []
    for u in units:
        warn_days, crit_days = thresholds.get((u.blood_bank_id, u.blood_group_id, u.component_id), (7, 3))
        remaining = (u.expiry_date - today).days
        category = (
            "Expired"
            if u.inventory_status == "Expired" or remaining < 0
            else classify_expiry_window(remaining, warn_days, crit_days)
        )
        rows.append(
            {
                "id": u.id,
                "unit_reference": u.unit_reference,
                "blood_group": u.blood_group.display_name,
                "component": u.component.component_name,
                "collection_date": u.collection_date,
                "expiry_date": u.expiry_date,
                "remaining_days": remaining,
                "warning_window_days": warn_days,
                "critical_window_days": crit_days,
                "expiry_category": category,
                "inventory_status": u.inventory_status,
                "storage_location": u.storage_location,
            }
        )
    return pd.DataFrame(rows)


def sweep_expired_units(
    session: Session,
    blood_bank_id: Optional[int] = None,
    actor: str = "admin",
    as_of: Optional[date] = None,
) -> list[str]:
    """Transition any past-expiry active units to 'Expired' with full transaction audit trail."""
    today = as_of or date.today()
    stmt = select(BloodUnit).where(
        BloodUnit.inventory_status.in_(["Released", "Testing Pending", "Quarantined"]),
        BloodUnit.expiry_date < today,
    )
    if blood_bank_id:
        stmt = stmt.where(BloodUnit.blood_bank_id == blood_bank_id)

    expired_units = session.scalars(stmt).all()
    transitioned: list[str] = []
    for u in expired_units:
        prev = u.inventory_status
        u.inventory_status = "Expired"
        session.add(
            InventoryTransaction(
                unit_id=u.id,
                transaction_type="EXPIRED",
                previous_status=prev,
                new_status="Expired",
                reference_type="EXPIRY_SWEEP",
                reference_id=today.isoformat(),
                quantity=1,
                reason=f"Unit passed expiry date ({u.expiry_date.isoformat()}) without issue",
                performed_by=actor,
            )
        )
        transitioned.append(u.unit_reference)

    if transitioned:
        log_audit(
            session,
            action="EXPIRY_SWEEP",
            entity_type="blood_unit",
            entity_id=f"{len(transitioned)}_units",
            details=f"Marked {len(transitioned)} past-expiry unit(s) as Expired.",
            actor_name=actor,
        )
    return transitioned


def record_discard_transaction(
    session: Session,
    unit_id: int,
    reason: str,
    actor: str = "admin",
) -> BloodUnit:
    """Record an explicit, audited discard transaction instead of deleting a unit."""
    if not reason or not reason.strip():
        raise DomainValidationError("A discard reason is mandatory.")
    unit = session.get(BloodUnit, unit_id)
    if not unit:
        raise DomainValidationError(f"Blood unit ID {unit_id} not found.")
    if unit.inventory_status in ("Issued", "Discarded"):
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' in status '{unit.inventory_status}' cannot be discarded."
        )

    prev = unit.inventory_status
    unit.inventory_status = "Discarded"
    session.add(
        InventoryTransaction(
            unit_id=unit.id,
            transaction_type="DISCARDED",
            previous_status=prev,
            new_status="Discarded",
            reference_type="DISCARD",
            reference_id=unit.unit_reference,
            quantity=1,
            reason=reason.strip(),
            performed_by=actor,
        )
    )
    log_audit(
        session,
        action="DISCARD_UNIT",
        entity_type="blood_unit",
        entity_id=unit.unit_reference,
        details=f"{prev} -> Discarded. Reason: {reason.strip()}",
        actor_name=actor,
    )
    return unit


def get_wastage_history_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
) -> pd.DataFrame:
    """Return historical expired and discarded transactions for wastage intelligence."""
    stmt = (
        select(InventoryTransaction)
        .options(
            joinedload(InventoryTransaction.unit).joinedload(BloodUnit.blood_group),
            joinedload(InventoryTransaction.unit).joinedload(BloodUnit.component),
        )
        .where(InventoryTransaction.transaction_type.in_(["EXPIRED", "DISCARDED"]))
        .order_by(InventoryTransaction.created_at.desc())
    )
    txs = session.scalars(stmt).all()
    rows = []
    for tx in txs:
        u = tx.unit
        if blood_bank_id and u.blood_bank_id != blood_bank_id:
            continue
        rows.append(
            {
                "transaction_id": tx.id,
                "unit_reference": u.unit_reference,
                "blood_group": u.blood_group.display_name,
                "component": u.component.component_name,
                "event_type": tx.transaction_type,
                "previous_status": tx.previous_status or "",
                "reason": tx.reason,
                "performed_by": tx.performed_by,
                "event_date": tx.created_at.date(),
                "event_month": tx.created_at.strftime("%Y-%m"),
            }
        )
    return pd.DataFrame(rows)
