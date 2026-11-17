"""Automated tests for Module 6 — FEFO Allocation Engine & Rollback Integrity."""

from __future__ import annotations

from datetime import date, timedelta
import pytest
from sqlalchemy import select

from backend.models import BloodAllocation
from backend.schemas import BloodRequestCreate
from backend.services.allocation_service import (
    confirm_fefo_allocation,
    preview_fefo_allocation,
    reverse_allocation,
)
from backend.services.request_service import approve_request, create_blood_request
from backend.validators.integrity import DomainValidationError
from tests.conftest import make_demo_donation, make_demo_unit


def test_fefo_ordering_excludes_expired_and_unreleased(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_id, "40", "O+", days_ago=15)

    # Expired unit (must be excluded)
    make_demo_unit(session, bank_id, don.donation_reference, "SV-EXP", "O+", expires_in_days=-1)
    # Unreleased unit (must be excluded)
    make_demo_unit(
        session, bank_id, don.donation_reference, "SV-PEND", "O+",
        expires_in_days=2, screening_status="Pending", inventory_status="Testing Pending",
    )
    # Valid released units with different expiry dates
    make_demo_unit(session, bank_id, don.donation_reference, "SV-LATE", "O+", expires_in_days=25)
    make_demo_unit(session, bank_id, don.donation_reference, "SV-EARLY", "O+", expires_in_days=4)
    make_demo_unit(session, bank_id, don.donation_reference, "SV-MID", "O+", expires_in_days=10)

    req = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-FEFO-1",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="O+",
            component_name="Red Blood Cells (RBC)",
            required_quantity=2,
            urgency="Urgent",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
    )
    approve_request(session, req.id)

    preview = preview_fefo_allocation(session, req.id)
    refs_order = [u["unit_reference"] for u in preview.proposed_units]
    assert refs_order == ["SV-EARLY", "SV-MID"]
    assert preview.unfulfilled_quantity == 0
    assert not preview.is_clinically_validated

    # Human approval required when no validated clinical policy is configured
    with pytest.raises(DomainValidationError, match="Explicit human approval confirmation"):
        confirm_fefo_allocation(session, req.id, human_approval_confirmed=False)

    res = confirm_fefo_allocation(session, req.id, human_approval_confirmed=True)
    assert res["allocated_units"] == ["SV-EARLY", "SV-MID"]
    assert res["request_status"] == "Fully Allocated"


def test_reserved_unit_cannot_be_double_allocated_and_shortfall_tracked(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_id, "41", "A-", days_ago=5)

    u1 = make_demo_unit(session, bank_id, don.donation_reference, "SV-SINGLE", "A-", expires_in_days=10)

    req1 = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-FEFO-2A",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="A-",
            component_name="Red Blood Cells (RBC)",
            required_quantity=1,
            urgency="Urgent",
            request_date=date.today(),
            required_date=date.today(),
        ),
    )
    req2 = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-FEFO-2B",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="A-",
            component_name="Red Blood Cells (RBC)",
            required_quantity=3,
            urgency="Routine",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=2),
        ),
    )
    approve_request(session, req1.id)
    approve_request(session, req2.id)

    confirm_fefo_allocation(session, req1.id, human_approval_confirmed=True)
    assert u1.inventory_status == "Reserved"

    # Attempt to allocate same reserved unit explicitly fails
    with pytest.raises(DomainValidationError, match="cannot be allocated"):
        confirm_fefo_allocation(session, req2.id, unit_ids=[u1.id], human_approval_confirmed=True)

    # Preview on req2 sees 0 units available and returns exact shortfall of 3
    preview2 = preview_fefo_allocation(session, req2.id)
    assert len(preview2.proposed_units) == 0
    assert preview2.unfulfilled_quantity == 3


def test_allocation_rollback_restores_inventory_consistency(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_id, "42", "B-", days_ago=3)
    u1 = make_demo_unit(session, bank_id, don.donation_reference, "SV-ROLL-1", "B-", expires_in_days=15)

    req = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-ROLL-1",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="B-",
            component_name="Red Blood Cells (RBC)",
            required_quantity=1,
            urgency="Priority",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
    )
    approve_request(session, req.id)
    confirm_fefo_allocation(session, req.id, human_approval_confirmed=True)
    assert u1.inventory_status == "Reserved"
    assert req.fulfilled_quantity == 1

    alloc = session.scalar(select(BloodAllocation).where(BloodAllocation.request_id == req.id))
    assert alloc is not None
    reverse_allocation(session, alloc.id, "Surgery rescheduled", actor="pytest")

    assert alloc.allocation_status == "Reversed"
    assert u1.inventory_status == "Released"
    assert req.fulfilled_quantity == 0
    assert req.status == "Approved"
