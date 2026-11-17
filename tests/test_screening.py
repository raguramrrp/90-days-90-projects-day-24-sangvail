"""Automated tests for Module 4 — Screening & Release Controls."""

from __future__ import annotations

import pytest

from backend.schemas import ScreeningDecision
from backend.services.screening_service import record_screening_decision
from backend.validators.integrity import DomainValidationError, assert_unit_can_be_issued
from tests.conftest import make_demo_donation, make_demo_unit


def test_pending_and_quarantined_units_cannot_be_issued(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "20", "O+")

    pending = make_demo_unit(
        session, bank_id, don.donation_reference, "SV-SCR-P1", "O+",
        screening_status="Pending", inventory_status="Testing Pending",
    )
    quarantined = make_demo_unit(
        session, bank_id, don.donation_reference, "SV-SCR-Q1", "O+",
        screening_status="Quarantined", inventory_status="Quarantined",
    )

    with pytest.raises(DomainValidationError, match="cannot be issued"):
        assert_unit_can_be_issued(pending)
    with pytest.raises(DomainValidationError, match="cannot be issued"):
        assert_unit_can_be_issued(quarantined)


def test_rejected_unit_cannot_be_released(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "21", "B-")

    unit = make_demo_unit(
        session, bank_id, don.donation_reference, "SV-SCR-R1", "B-",
        screening_status="Pending", inventory_status="Testing Pending",
    )
    record_screening_decision(
        session,
        ScreeningDecision(
            unit_id=unit.id,
            new_screening_status="Rejected",
            target_inventory_status="Rejected",
            result_reference="SCR-REJ-01",
            reviewed_by="qa_lead",
        ),
        actor="qa_lead",
    )
    assert unit.inventory_status == "Rejected"

    with pytest.raises(DomainValidationError, match="Rejected and can never be transitioned to Released"):
        record_screening_decision(
            session,
            ScreeningDecision(
                unit_id=unit.id,
                new_screening_status="Cleared",
                target_inventory_status="Released",
                result_reference="SCR-OVR-01",
                reviewed_by="qa_lead",
            ),
            actor="qa_lead",
        )


def test_cleared_unit_becomes_eligible_after_authorized_release(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "22", "A+")

    unit = make_demo_unit(
        session, bank_id, don.donation_reference, "SV-SCR-C1", "A+",
        screening_status="Pending", inventory_status="Testing Pending",
    )
    record_screening_decision(
        session,
        ScreeningDecision(
            unit_id=unit.id,
            new_screening_status="Cleared",
            target_inventory_status="Released",
            result_reference="SCR-CLR-01",
            reviewed_by="qa_lead",
        ),
        actor="qa_lead",
    )
    assert unit.inventory_status == "Released"
    assert unit.screening_status == "Cleared"
    assert_unit_can_be_issued(unit)
