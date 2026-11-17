"""Operational Data Quality Centre: 14 automated integrity checks & controlled remediation."""

from __future__ import annotations

from datetime import date
from typing import Optional
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import VALID_INVENTORY_TRANSITIONS
from backend.auth import log_audit
from backend.models import (
    BloodAllocation,
    BloodRequest,
    BloodUnit,
    Donation,
    InventoryTransaction,
)


def run_data_quality_checks(
    session: Session,
    blood_bank_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> dict:
    """
    Execute all 14 operational data quality validation checks against the live database.

    Returns overall score, summary counts, per-check results, and row-level failure records.
    """
    today = as_of or date.today()
    unit_stmt = select(BloodUnit).options(
        joinedload(BloodUnit.blood_group),
        joinedload(BloodUnit.component),
        joinedload(BloodUnit.donation),
    )
    req_stmt = select(BloodRequest)
    if blood_bank_id:
        unit_stmt = unit_stmt.where(BloodUnit.blood_bank_id == blood_bank_id)
        req_stmt = req_stmt.where(BloodRequest.blood_bank_id == blood_bank_id)

    units = session.scalars(unit_stmt).all()
    requests = session.scalars(req_stmt).all()
    unit_ids = {u.id for u in units}

    allocations = session.scalars(select(BloodAllocation)).all()
    if blood_bank_id:
        allocations = [a for a in allocations if a.unit_id in unit_ids]

    transactions = session.scalars(select(InventoryTransaction).order_by(InventoryTransaction.created_at.asc())).all()
    if blood_bank_id:
        transactions = [t for t in transactions if t.unit_id in unit_ids]

    donations_ids = set(session.scalars(select(Donation.id)).all())

    active_reserved_unit_ids = {a.unit_id for a in allocations if a.allocation_status == "Reserved"}
    issued_tx_unit_ids = {t.unit_id for t in transactions if t.transaction_type == "ISSUED"}
    alloc_count_by_req: dict[int, int] = {}
    for a in allocations:
        if a.allocation_status in ("Reserved", "Issued"):
            alloc_count_by_req[a.request_id] = alloc_count_by_req.get(a.request_id, 0) + 1

    issues: list[dict] = []
    check_summaries: list[dict] = []

    def _record_check(
        code: str,
        name: str,
        severity: str,
        records_checked: int,
        failed_items: list[dict],
    ) -> None:
        check_summaries.append(
            {
                "check_code": code,
                "check_name": name,
                "severity": severity,
                "records_checked": records_checked,
                "failed_count": len(failed_items),
                "status": "Pass" if not failed_items else ("Critical" if severity == "Critical" else "Warning"),
            }
        )
        issues.extend(failed_items)

    # 1. Duplicate unit IDs
    unit_ref_counts: dict[str, int] = {}
    for u in units:
        unit_ref_counts[u.unit_reference] = unit_ref_counts.get(u.unit_reference, 0) + 1
    dup_units = [
        {
            "check_code": "DQ-01",
            "severity": "Critical",
            "entity_type": "blood_unit",
            "entity_id": ref,
            "description": f"Duplicate unit reference '{ref}' occurs {cnt} times.",
            "remediation": "Manual review required",
        }
        for ref, cnt in unit_ref_counts.items()
        if cnt > 1
    ]
    _record_check("DQ-01", "Duplicate unit IDs", "Critical", len(units), dup_units)

    # 2. Missing donation references
    missing_don = [
        {
            "check_code": "DQ-02",
            "severity": "Critical",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": "Blood unit is missing a valid donation reference.",
            "remediation": "Link valid donation",
        }
        for u in units
        if u.donation_id is None or u.donation_id not in donations_ids
    ]
    _record_check("DQ-02", "Missing donation references", "Critical", len(units), missing_don)

    # 3. Missing blood groups
    missing_bg = [
        {
            "check_code": "DQ-03",
            "severity": "Critical",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": "Blood unit has no assigned blood group.",
            "remediation": "Assign verified blood group",
        }
        for u in units
        if u.blood_group_id is None or u.blood_group is None
    ]
    _record_check("DQ-03", "Missing blood groups", "Critical", len(units), missing_bg)

    # 4. Invalid expiry dates
    invalid_exp = [
        {
            "check_code": "DQ-04",
            "severity": "Critical",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": f"Expiry date ({u.expiry_date}) is on or before collection date ({u.collection_date}).",
            "remediation": "Quarantine and verify dates",
        }
        for u in units
        if u.expiry_date <= u.collection_date
    ]
    _record_check("DQ-04", "Invalid expiry dates", "Critical", len(units), invalid_exp)

    # 5. Processing date before collection date
    invalid_proc = [
        {
            "check_code": "DQ-05",
            "severity": "Critical",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": f"Processing date ({u.processing_date}) precedes collection date ({u.collection_date}).",
            "remediation": "Correct processing timestamp",
        }
        for u in units
        if u.processing_date is not None and u.processing_date < u.collection_date
    ]
    _record_check("DQ-05", "Processing date before collection date", "Critical", len(units), invalid_proc)

    # 6. Units marked available without release/clearance
    unreleased_avail = [
        {
            "check_code": "DQ-06",
            "severity": "Critical",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": f"Unit is marked Released but screening status is '{u.screening_status}'.",
            "remediation": "Quarantine unit until cleared",
        }
        for u in units
        if u.inventory_status == "Released" and u.screening_status != "Cleared"
    ]
    _record_check("DQ-06", "Units marked Released without screening clearance", "Critical", len(units), unreleased_avail)

    # 7. Reserved units without active allocation records
    orphan_reserved = [
        {
            "check_code": "DQ-07",
            "severity": "Warning",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": "Unit has status 'Reserved' without a matching active allocation record.",
            "remediation": "Restore unit to Released (or Expired)",
        }
        for u in units
        if u.inventory_status == "Reserved" and u.id not in active_reserved_unit_ids
    ]
    _record_check("DQ-07", "Reserved units without active allocations", "Warning", len(units), orphan_reserved)

    # 8. Issued units without ISSUED transaction record
    orphan_issued = [
        {
            "check_code": "DQ-08",
            "severity": "Warning",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": "Unit is marked 'Issued' without a corresponding ISSUED inventory transaction.",
            "remediation": "Record audit reconciliation note",
        }
        for u in units
        if u.inventory_status == "Issued" and u.id not in issued_tx_unit_ids
    ]
    _record_check("DQ-08", "Issued units without issue transactions", "Warning", len(units), orphan_issued)

    # 9. Negative stock / negative request quantities
    neg_records = [
        {
            "check_code": "DQ-09",
            "severity": "Critical",
            "entity_type": "blood_request",
            "entity_id": r.request_reference,
            "description": f"Request has invalid quantity (required={r.required_quantity}, fulfilled={r.fulfilled_quantity}).",
            "remediation": "Audit request quantities",
        }
        for r in requests
        if r.required_quantity <= 0 or r.fulfilled_quantity < 0
    ]
    _record_check("DQ-09", "Negative stock or invalid quantities", "Critical", len(requests), neg_records)

    # 10. Duplicate request IDs
    req_ref_counts: dict[str, int] = {}
    for r in requests:
        req_ref_counts[r.request_reference] = req_ref_counts.get(r.request_reference, 0) + 1
    dup_reqs = [
        {
            "check_code": "DQ-10",
            "severity": "Critical",
            "entity_type": "blood_request",
            "entity_id": ref,
            "description": f"Duplicate request reference '{ref}' occurs {cnt} times.",
            "remediation": "Deduplicate request reference",
        }
        for ref, cnt in req_ref_counts.items()
        if cnt > 1
    ]
    _record_check("DQ-10", "Duplicate request IDs", "Critical", len(requests), dup_reqs)

    # 11. Allocations exceeding requested quantities
    over_alloc = []
    for r in requests:
        actual_allocs = alloc_count_by_req.get(r.id, 0)
        if r.fulfilled_quantity > r.required_quantity or actual_allocs > r.required_quantity:
            over_alloc.append(
                {
                    "check_code": "DQ-11",
                    "severity": "Critical",
                    "entity_type": "blood_request",
                    "entity_id": r.request_reference,
                    "description": (
                        f"Allocated/fulfilled count ({max(r.fulfilled_quantity, actual_allocs)}) "
                        f"exceeds required quantity ({r.required_quantity})."
                    ),
                    "remediation": "Reverse excess allocations",
                }
            )
    _record_check("DQ-11", "Allocations exceeding requested quantities", "Critical", len(requests), over_alloc)

    # 12. Transactions with missing references
    missing_tx_ref = [
        {
            "check_code": "DQ-12",
            "severity": "Warning",
            "entity_type": "inventory_transaction",
            "entity_id": f"TX-{t.id}",
            "description": f"Transaction {t.transaction_type} is missing reference_id or actor.",
            "remediation": "Review transaction log",
        }
        for t in transactions
        if not t.reference_id or not t.performed_by
    ]
    _record_check("DQ-12", "Transactions with missing references", "Warning", len(transactions), missing_tx_ref)

    # 13. Inconsistent status transitions in transaction log
    bad_transitions = []
    for t in transactions:
        if t.previous_status and t.previous_status != t.new_status:
            allowed = VALID_INVENTORY_TRANSITIONS.get(t.previous_status, set())
            if t.new_status not in allowed:
                bad_transitions.append(
                    {
                        "check_code": "DQ-13",
                        "severity": "Warning",
                        "entity_type": "inventory_transaction",
                        "entity_id": f"TX-{t.id}",
                        "description": f"Unexpected transition {t.previous_status} -> {t.new_status}.",
                        "remediation": "Audit historical transition",
                    }
                )
    _record_check("DQ-13", "Inconsistent status transitions", "Warning", len(transactions), bad_transitions)

    # 14. Expired units still marked Released/Available
    expired_released = [
        {
            "check_code": "DQ-14",
            "severity": "Critical",
            "entity_type": "blood_unit",
            "entity_id": u.unit_reference,
            "description": f"Unit expired on {u.expiry_date.isoformat()} but is still marked 'Released'.",
            "remediation": "Run controlled expiry transition",
        }
        for u in units
        if u.inventory_status == "Released" and u.expiry_date < today
    ]
    _record_check("DQ-14", "Expired units still marked Released", "Critical", len(units), expired_released)

    total_checks = len(check_summaries)
    passed_checks = sum(1 for c in check_summaries if c["status"] == "Pass")
    failed_checks = total_checks - passed_checks
    critical_count = sum(1 for i in issues if i["severity"] == "Critical")
    warning_count = sum(1 for i in issues if i["severity"] == "Warning")
    total_records_checked = len(units) + len(requests) + len(transactions)

    # Weighted score: base 100 minus penalty for failed checks and issue density
    if total_records_checked == 0:
        score = 100.0
    else:
        check_pass_ratio = passed_checks / total_checks
        issue_penalty = min(35.0, critical_count * 2.5 + warning_count * 0.75)
        score = round(max(0.0, min(100.0, check_pass_ratio * 100.0 - issue_penalty * 0.4)), 1)

    return {
        "overall_score": score,
        "total_records_checked": total_records_checked,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "critical_error_count": critical_count,
        "warning_count": warning_count,
        "checks_df": pd.DataFrame(check_summaries),
        "issues_df": pd.DataFrame(issues),
    }


def remediate_expired_released_unit(
    session: Session,
    unit_reference: str,
    actor: str = "admin",
) -> str:
    """Controlled, audited remediation for an expired unit still marked Released."""
    unit = session.scalar(select(BloodUnit).where(BloodUnit.unit_reference == unit_reference))
    if not unit:
        raise ValueError(f"Unit '{unit_reference}' not found.")
    prev = unit.inventory_status
    unit.inventory_status = "Expired"
    session.add(
        InventoryTransaction(
            unit_id=unit.id,
            transaction_type="EXPIRED",
            previous_status=prev,
            new_status="Expired",
            reference_type="DATA_QUALITY",
            reference_id="DQ-14",
            quantity=1,
            reason=f"Controlled remediation: expired unit ({unit.expiry_date}) transitioned from {prev} to Expired",
            performed_by=actor,
        )
    )
    log_audit(
        session,
        action="DQ_REMEDIATION_EXPIRED_UNIT",
        entity_type="blood_unit",
        entity_id=unit.unit_reference,
        details=f"Transitioned {prev} -> Expired via Data Quality Centre",
        actor_name=actor,
    )
    return f"Unit {unit.unit_reference} safely transitioned to Expired with audit trail."


def remediate_unreleased_quarantine_unit(
    session: Session,
    unit_reference: str,
    actor: str = "admin",
) -> str:
    """Controlled, audited remediation moving an uncleared Released unit into Quarantine."""
    unit = session.scalar(select(BloodUnit).where(BloodUnit.unit_reference == unit_reference))
    if not unit:
        raise ValueError(f"Unit '{unit_reference}' not found.")
    prev = unit.inventory_status
    unit.inventory_status = "Quarantined"
    session.add(
        InventoryTransaction(
            unit_id=unit.id,
            transaction_type="QUARANTINED",
            previous_status=prev,
            new_status="Quarantined",
            reference_type="DATA_QUALITY",
            reference_id="DQ-06",
            quantity=1,
            reason="Controlled remediation: unit lacked cleared screening status and was moved to Quarantine",
            performed_by=actor,
        )
    )
    log_audit(
        session,
        action="DQ_REMEDIATION_QUARANTINE",
        entity_type="blood_unit",
        entity_id=unit.unit_reference,
        details=f"Transitioned {prev} -> Quarantined via Data Quality Centre",
        actor_name=actor,
    )
    return f"Unit {unit.unit_reference} moved to Quarantined with audit trail."
