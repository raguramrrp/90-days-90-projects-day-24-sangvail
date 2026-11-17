"""FEFO (First Expiry, First Out) inventory allocation and policy hook service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, Protocol
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.auth import log_audit
from backend.models import BloodAllocation, BloodRequest, BloodUnit, InventoryTransaction
from backend.validators.integrity import DomainValidationError, assert_unit_eligible_for_allocation


class CompatibilityPolicy(Protocol):
    """Integration point for an authorized, externally validated clinical compatibility policy."""

    policy_name: str
    is_clinically_validated: bool
    advisory_message: str

    def filter_eligible_units(self, request: BloodRequest, candidates: list[BloodUnit]) -> list[BloodUnit]:
        ...


@dataclass(frozen=True)
class AdministrativeExactMatchPolicy:
    """
    Default administrative demonstration policy.

    Matches only identical blood-group label and component ID without asserting clinical
    transfusion compatibility. Actual clinical compatibility and cross-matching must always
    be performed by authorized laboratory personnel under validated institutional SOPs.
    """

    policy_name: str = "Administrative Exact-Label Match (Non-Clinical)"
    is_clinically_validated: bool = False
    advisory_message: str = (
        "Administrative Allocation Mode: No validated clinical compatibility policy is configured. "
        "Proposed units match the requested blood-group label and component strictly for operational "
        "planning. Authorized personnel must verify clinical compatibility before transfusion."
    )

    def filter_eligible_units(self, request: BloodRequest, candidates: list[BloodUnit]) -> list[BloodUnit]:
        return [
            u
            for u in candidates
            if u.blood_group_id == request.blood_group_id and u.component_id == request.component_id
        ]


@dataclass
class AllocationPreview:
    request_id: int
    request_reference: str
    requested_remaining: int
    proposed_units: list[dict]
    unfulfilled_quantity: int
    policy_name: str
    is_clinically_validated: bool
    advisory_message: str


def _fetch_eligible_released_units(
    session: Session,
    request: BloodRequest,
    policy: CompatibilityPolicy,
    as_of: date,
) -> list[BloodUnit]:
    """Fetch released, cleared, non-expired units ordered strictly by earliest expiry (FEFO)."""
    stmt = (
        select(BloodUnit)
        .options(joinedload(BloodUnit.blood_group), joinedload(BloodUnit.component))
        .where(
            BloodUnit.blood_bank_id == request.blood_bank_id,
            BloodUnit.inventory_status == "Released",
            BloodUnit.screening_status == "Cleared",
            BloodUnit.expiry_date >= as_of,
        )
        .order_by(BloodUnit.expiry_date.asc(), BloodUnit.collection_date.asc(), BloodUnit.id.asc())
    )
    candidates = list(session.scalars(stmt).all())
    eligible = policy.filter_eligible_units(request, candidates)

    # Defensive double-check against any active reservation on the unit
    active_reserved_ids = set(
        session.scalars(
            select(BloodAllocation.unit_id).where(BloodAllocation.allocation_status == "Reserved")
        ).all()
    )
    return [u for u in eligible if u.id not in active_reserved_ids]


def preview_fefo_allocation(
    session: Session,
    request_id: int,
    quantity: Optional[int] = None,
    policy: Optional[CompatibilityPolicy] = None,
    as_of: Optional[date] = None,
) -> AllocationPreview:
    """Compute a dry-run FEFO allocation proposal without mutating the database."""
    req = session.scalar(
        select(BloodRequest)
        .options(joinedload(BloodRequest.blood_group), joinedload(BloodRequest.component))
        .where(BloodRequest.id == request_id)
    )
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")
    if req.status not in ("Approved", "Partially Allocated"):
        raise DomainValidationError(
            f"Request '{req.request_reference}' must be 'Approved' or 'Partially Allocated' before allocation "
            f"(current status: '{req.status}')."
        )

    remaining = req.required_quantity - req.fulfilled_quantity
    if remaining <= 0:
        raise DomainValidationError(f"Request '{req.request_reference}' is already fully allocated.")

    target_qty = min(quantity, remaining) if quantity is not None else remaining
    if target_qty <= 0:
        raise DomainValidationError("Allocation quantity must be greater than zero.")

    active_policy = policy or AdministrativeExactMatchPolicy()
    today = as_of or date.today()
    eligible_units = _fetch_eligible_released_units(session, req, active_policy, today)
    selected = eligible_units[:target_qty]
    unfulfilled = max(0, target_qty - len(selected))

    proposed = [
        {
            "unit_id": u.id,
            "unit_reference": u.unit_reference,
            "blood_group": u.blood_group.display_name,
            "component": u.component.component_name,
            "collection_date": u.collection_date,
            "expiry_date": u.expiry_date,
            "remaining_days": (u.expiry_date - today).days,
            "storage_location": u.storage_location,
            "fefo_rank": idx,
        }
        for idx, u in enumerate(selected, start=1)
    ]

    return AllocationPreview(
        request_id=req.id,
        request_reference=req.request_reference,
        requested_remaining=target_qty,
        proposed_units=proposed,
        unfulfilled_quantity=unfulfilled,
        policy_name=active_policy.policy_name,
        is_clinically_validated=active_policy.is_clinically_validated,
        advisory_message=active_policy.advisory_message,
    )


def confirm_fefo_allocation(
    session: Session,
    request_id: int,
    actor: str = "admin",
    quantity: Optional[int] = None,
    unit_ids: Optional[list[int]] = None,
    policy: Optional[CompatibilityPolicy] = None,
    human_approval_confirmed: bool = True,
    as_of: Optional[date] = None,
) -> dict:
    """Atomically reserve eligible units using FEFO and update request & transaction state."""
    active_policy = policy or AdministrativeExactMatchPolicy()
    if not active_policy.is_clinically_validated and not human_approval_confirmed:
        raise DomainValidationError(
            "Explicit human approval confirmation is required when operating without a validated clinical policy."
        )

    today = as_of or date.today()
    req = session.get(BloodRequest, request_id)
    if not req:
        raise DomainValidationError(f"Blood request ID {request_id} not found.")
    if req.status not in ("Approved", "Partially Allocated"):
        raise DomainValidationError(
            f"Request '{req.request_reference}' cannot be allocated from status '{req.status}'."
        )

    remaining = req.required_quantity - req.fulfilled_quantity
    if remaining <= 0:
        raise DomainValidationError(f"Request '{req.request_reference}' is already fully allocated.")

    target_qty = min(quantity, remaining) if quantity is not None else remaining
    if target_qty <= 0:
        raise DomainValidationError("Allocation quantity must be positive.")

    eligible_units = _fetch_eligible_released_units(session, req, active_policy, today)
    if unit_ids is not None:
        eligible_map = {u.id: u for u in eligible_units}
        selected = []
        for uid in unit_ids:
            if uid not in eligible_map:
                unit_check = session.get(BloodUnit, uid)
                if unit_check:
                    assert_unit_eligible_for_allocation(unit_check, as_of=today)
                raise DomainValidationError(f"Unit ID {uid} is not eligible for request '{req.request_reference}'.")
            selected.append(eligible_map[uid])
        if len(selected) > remaining:
            raise DomainValidationError(
                f"Cannot allocate {len(selected)} units; only {remaining} remaining for request '{req.request_reference}'."
            )
    else:
        selected = eligible_units[:target_qty]

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    allocated_refs: list[str] = []
    for unit in selected:
        assert_unit_eligible_for_allocation(unit, as_of=today)
        prev_status = unit.inventory_status
        unit.inventory_status = "Reserved"

        alloc = BloodAllocation(
            request_id=req.id,
            unit_id=unit.id,
            allocation_date=now_utc,
            allocated_by=actor,
            allocation_status="Reserved",
            policy_acknowledged=human_approval_confirmed,
            notes=f"FEFO allocation under {active_policy.policy_name}",
        )
        session.add(alloc)
        session.add(
            InventoryTransaction(
                unit_id=unit.id,
                transaction_type="RESERVED",
                previous_status=prev_status,
                new_status="Reserved",
                reference_type="REQUEST",
                reference_id=req.request_reference,
                quantity=1,
                reason=f"FEFO reserved for request {req.request_reference}",
                performed_by=actor,
            )
        )
        allocated_refs.append(unit.unit_reference)

    req.fulfilled_quantity += len(selected)
    if req.fulfilled_quantity > req.required_quantity:
        raise DomainValidationError("Allocation would exceed requested quantity.")

    if req.fulfilled_quantity == req.required_quantity:
        req.status = "Fully Allocated"
    elif req.fulfilled_quantity > 0:
        req.status = "Partially Allocated"

    unfulfilled_after = max(0, req.required_quantity - req.fulfilled_quantity)
    log_audit(
        session,
        action="CONFIRM_FEFO_ALLOCATION",
        entity_type="blood_request",
        entity_id=req.request_reference,
        details=f"Allocated {len(selected)} unit(s): {', '.join(allocated_refs)}. Remaining: {unfulfilled_after}.",
        actor_name=actor,
    )
    session.flush()
    return {
        "request_reference": req.request_reference,
        "allocated_count": len(selected),
        "allocated_units": allocated_refs,
        "unfulfilled_quantity": unfulfilled_after,
        "request_status": req.status,
    }


def reverse_allocation(
    session: Session,
    allocation_id: int,
    reason: str,
    actor: str = "admin",
    as_of: Optional[date] = None,
) -> BloodAllocation:
    """Roll back a reserved allocation, restoring unit availability and updating request counts."""
    alloc = session.scalar(
        select(BloodAllocation)
        .options(joinedload(BloodAllocation.unit), joinedload(BloodAllocation.request))
        .where(BloodAllocation.id == allocation_id)
    )
    if not alloc:
        raise DomainValidationError(f"Allocation ID {allocation_id} not found.")
    if alloc.allocation_status != "Reserved":
        raise DomainValidationError(
            f"Only 'Reserved' allocations can be reversed (current status: '{alloc.allocation_status}')."
        )

    today = as_of or date.today()
    unit = alloc.unit
    req = alloc.request
    prev_status = unit.inventory_status
    restored_status = "Expired" if unit.expiry_date < today else "Released"
    unit.inventory_status = restored_status
    alloc.allocation_status = "Reversed"
    alloc.notes = f"{alloc.notes} | Reversed: {reason}".strip(" |")

    req.fulfilled_quantity = max(0, req.fulfilled_quantity - 1)
    if req.fulfilled_quantity == 0:
        req.status = "Approved"
    elif req.fulfilled_quantity < req.required_quantity:
        req.status = "Partially Allocated"

    session.add(
        InventoryTransaction(
            unit_id=unit.id,
            transaction_type="ALLOCATION_REVERSED",
            previous_status=prev_status,
            new_status=restored_status,
            reference_type="REQUEST",
            reference_id=req.request_reference,
            quantity=1,
            reason=reason or f"Allocation reversed for request {req.request_reference}",
            performed_by=actor,
        )
    )
    log_audit(
        session,
        action="REVERSE_ALLOCATION",
        entity_type="blood_allocation",
        entity_id=str(alloc.id),
        details=f"Unit {unit.unit_reference} restored to {restored_status} from request {req.request_reference}.",
        actor_name=actor,
    )
    session.flush()
    return alloc
