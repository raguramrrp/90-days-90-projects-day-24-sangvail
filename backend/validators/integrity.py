"""Domain integrity checks and state transition validators."""

from __future__ import annotations

from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import VALID_INVENTORY_TRANSITIONS, VALID_REQUEST_TRANSITIONS
from backend.models import BloodComponent, BloodGroup, BloodUnit


class DomainValidationError(ValueError):
    """Raised when a domain rule or operational guardrail is violated."""


def validate_inventory_transition(current_status: str, new_status: str) -> None:
    """Ensure a unit's inventory status transition is allowed by the state machine."""
    if current_status == new_status:
        return
    allowed = VALID_INVENTORY_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise DomainValidationError(
            f"Invalid inventory status transition from '{current_status}' to '{new_status}'. "
            f"Allowed targets: {sorted(allowed) or ['None (terminal state)']}."
        )


def validate_request_transition(current_status: str, new_status: str) -> None:
    """Ensure a blood request status transition is valid."""
    if current_status == new_status:
        return
    allowed = VALID_REQUEST_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise DomainValidationError(
            f"Invalid request status transition from '{current_status}' to '{new_status}'."
        )


def assert_unit_eligible_for_allocation(unit: BloodUnit, as_of: date | None = None) -> None:
    """Enforce strict eligibility before allocating or issuing a blood unit."""
    check_date = as_of or date.today()
    if unit.inventory_status != "Released":
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' has status '{unit.inventory_status}' and cannot be allocated. "
            "Only 'Released' units are eligible."
        )
    if unit.screening_status != "Cleared":
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' has screening status '{unit.screening_status}' and is not cleared."
        )
    if unit.expiry_date < check_date:
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' expired on {unit.expiry_date.isoformat()} and cannot be allocated."
        )


def assert_unit_can_be_issued(unit: BloodUnit, as_of: date | None = None) -> None:
    """Enforce that pending, quarantined, rejected, expired, or discarded units cannot be issued."""
    check_date = as_of or date.today()
    blocked_statuses = {"Collected", "Testing Pending", "Quarantined", "Rejected", "Expired", "Discarded", "Issued"}
    if unit.inventory_status in blocked_statuses:
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' cannot be issued from status '{unit.inventory_status}'."
        )
    if unit.screening_status != "Cleared":
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' cannot be issued without cleared screening status."
        )
    if unit.expiry_date < check_date:
        raise DomainValidationError(
            f"Unit '{unit.unit_reference}' expired on {unit.expiry_date.isoformat()} and cannot be issued."
        )


def get_blood_group_by_name(session: Session, display_name: str) -> BloodGroup:
    bg = session.scalar(select(BloodGroup).where(BloodGroup.display_name == display_name))
    if not bg:
        raise DomainValidationError(f"Unknown blood group '{display_name}'.")
    return bg


def get_component_by_name(session: Session, component_name: str) -> BloodComponent:
    comp = session.scalar(select(BloodComponent).where(BloodComponent.component_name == component_name))
    if not comp:
        raise DomainValidationError(f"Unknown blood component '{component_name}'.")
    return comp
