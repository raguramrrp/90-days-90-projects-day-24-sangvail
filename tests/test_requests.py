"""Automated tests for Module 5 — Hospital Blood Request Workflow."""

from __future__ import annotations

from datetime import date, timedelta
import pytest
from pydantic import ValidationError

from backend.schemas import BloodRequestCreate
from backend.services.allocation_service import confirm_fefo_allocation
from backend.services.request_service import (
    approve_request,
    cancel_request,
    create_blood_request,
    mark_request_issued,
    reject_request,
)
from backend.validators.integrity import DomainValidationError
from tests.conftest import make_demo_donation, make_demo_unit


def test_create_approve_and_reject_request(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))

    req = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-T001",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="O+",
            component_name="Red Blood Cells (RBC)",
            required_quantity=3,
            urgency="Urgent",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
        actor="pytest",
    )
    assert req.status == "Submitted"
    approve_request(session, req.id, actor="pytest")
    assert req.status == "Approved"

    req2 = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-T002",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="A+",
            component_name="Platelets",
            required_quantity=2,
            urgency="Routine",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
    )
    with pytest.raises(DomainValidationError, match="rejection reason is required"):
        reject_request(session, req2.id, "")
    reject_request(session, req2.id, "Duplicate order submitted by ward")
    assert req2.status == "Rejected"


def test_validate_required_quantity_and_prevent_over_fulfilment(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))

    with pytest.raises(ValidationError):
        BloodRequestCreate(
            request_reference="REQ-ZERO",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="O+",
            component_name="Red Blood Cells (RBC)",
            required_quantity=0,
            urgency="Routine",
            request_date=date.today(),
            required_date=date.today(),
        )

    don = make_demo_donation(session, bank_id, "30", "O+")
    u1 = make_demo_unit(session, bank_id, don.donation_reference, "SV-REQ-U1", "O+", expires_in_days=10)
    u2 = make_demo_unit(session, bank_id, don.donation_reference, "SV-REQ-U2", "O+", expires_in_days=15)

    req = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-T003",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="O+",
            component_name="Red Blood Cells (RBC)",
            required_quantity=1,
            urgency="Priority",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
    )
    approve_request(session, req.id)
    with pytest.raises(DomainValidationError, match="Cannot allocate 2 units"):
        confirm_fefo_allocation(session, req.id, unit_ids=[u1.id, u2.id], human_approval_confirmed=True)

    confirm_fefo_allocation(session, req.id, quantity=1, human_approval_confirmed=True)
    mark_request_issued(session, req.id, handover_note="Verified dispatch")
    assert req.status == "Issued"
    assert u1.inventory_status == "Issued"


def test_cancel_request_restores_reserved_inventory(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_id, "31", "B+")
    u1 = make_demo_unit(session, bank_id, don.donation_reference, "SV-CAN-U1", "B+", expires_in_days=12)

    req = create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-T004",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="B+",
            component_name="Red Blood Cells (RBC)",
            required_quantity=1,
            urgency="Routine",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
    )
    approve_request(session, req.id)
    confirm_fefo_allocation(session, req.id, quantity=1, human_approval_confirmed=True)
    assert u1.inventory_status == "Reserved"

    cancel_request(session, req.id, "Procedure postponed")
    assert req.status == "Cancelled"
    assert req.fulfilled_quantity == 0
    assert u1.inventory_status == "Released"
