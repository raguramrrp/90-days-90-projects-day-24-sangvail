"""Automated tests for Module 3 — Donations & Traceable Component Production."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas import DonationCreate
from backend.services.donation_service import (
    produce_component_units_from_donation,
    update_donation_status,
)
from backend.validators.integrity import DomainValidationError
from tests.conftest import make_demo_donation


def test_donation_workflow_and_multi_component_production(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "10", "AB+", days_ago=1)

    update_donation_status(session, don.id, "Processing", actor="pytest")
    units = produce_component_units_from_donation(
        session,
        donation_id=don.id,
        component_names=["Red Blood Cells (RBC)", "Fresh Frozen Plasma (FFP)"],
        storage_location="Cold Room A — Rack 1 (2-6°C)",
        actor="pytest",
    )
    assert len(units) == 2
    assert don.collection_status == "Completed"
    assert all(u.donation_id == don.id for u in units)
    assert all(u.inventory_status == "Testing Pending" for u in units)
    # Component-specific expiry dates differ (RBC 42d vs FFP 365d)
    assert units[1].expiry_date > units[0].expiry_date


def test_rejected_donation_cannot_produce_units(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "11", "A-", days_ago=1)
    update_donation_status(session, don.id, "Rejected", actor="pytest", notes="Low draw volume")

    with pytest.raises(DomainValidationError, match="cannot produce component units"):
        produce_component_units_from_donation(
            session,
            donation_id=don.id,
            component_names=["Red Blood Cells (RBC)"],
            storage_location="Cold Room A — Rack 1 (2-6°C)",
        )


def test_donation_rejects_negative_quantity(db_session):
    _, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    with pytest.raises(ValidationError):
        DonationCreate(
            donation_reference="DN-NEG",
            donor_reference="DNR-1",
            blood_bank_id=bank_id,
            donation_date="2026-01-01",
            collection_location="Suite A",
            collection_type="Whole Blood Collection",
            collected_quantity=-450,
            collection_staff="Tech",
        )
