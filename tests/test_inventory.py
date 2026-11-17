"""Automated tests for Module 2 — Unit-Level Inventory Management."""

from __future__ import annotations

from datetime import date, timedelta
import pytest
from pydantic import ValidationError

from backend.schemas import BloodUnitCreate
from backend.services.inventory_service import (
    create_blood_unit,
    get_stock_reconciliation,
    update_unit_status,
)
from backend.validators.integrity import DomainValidationError
from tests.conftest import make_demo_donation, make_demo_unit


def test_create_unit_and_reject_duplicate_id(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "01", "A+")

    u1 = make_demo_unit(session, bank_id, don.donation_reference, "SV-TEST-001", "A+")
    assert u1.id is not None

    with pytest.raises(DomainValidationError, match="Duplicate unit ID"):
        make_demo_unit(session, bank_id, don.donation_reference, "SV-TEST-001", "A+")


def test_validate_blood_group_and_component(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "02", "O+")

    with pytest.raises(ValidationError):
        BloodUnitCreate(
            unit_reference="SV-BAD-BG",
            donation_reference=don.donation_reference,
            blood_bank_id=bank_id,
            blood_group="Z+",
            component_name="Red Blood Cells (RBC)",
            collection_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
            storage_location="Cold Room A",
        )

    with pytest.raises(DomainValidationError, match="Unknown blood component"):
        create_blood_unit(
            session,
            BloodUnitCreate(
                unit_reference="SV-BAD-COMP",
                donation_reference=don.donation_reference,
                blood_bank_id=bank_id,
                blood_group="O+",
                component_name="Unknown Component",
                collection_date=date.today(),
                expiry_date=date.today() + timedelta(days=30),
                storage_location="Cold Room A",
            ),
        )


def test_prevent_invalid_dates_and_status_transitions(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "03", "B+")

    with pytest.raises(ValidationError, match="Processing date"):
        BloodUnitCreate(
            unit_reference="SV-BAD-DATE",
            donation_reference=don.donation_reference,
            blood_bank_id=bank_id,
            blood_group="B+",
            component_name="Red Blood Cells (RBC)",
            collection_date=date.today(),
            processing_date=date.today() - timedelta(days=1),
            expiry_date=date.today() + timedelta(days=20),
            storage_location="Cold Room A",
        )

    unit = make_demo_unit(
        session,
        bank_id,
        don.donation_reference,
        "SV-TRANS-01",
        "B+",
        screening_status="Pending",
        inventory_status="Testing Pending",
    )
    # Cannot jump directly from Testing Pending to Issued
    with pytest.raises(DomainValidationError, match="Invalid inventory status transition"):
        update_unit_status(session, unit.id, "Issued")

    # Cannot release without Cleared screening status
    with pytest.raises(DomainValidationError, match="cannot be released"):
        update_unit_status(session, unit.id, "Released")


def test_stock_reconciliation_excludes_non_available_units(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    don = make_demo_donation(session, bank_id, "04", "O-", days_ago=10)

    make_demo_unit(session, bank_id, don.donation_reference, "SV-REC-1", "O-", expires_in_days=15)
    make_demo_unit(
        session,
        bank_id,
        don.donation_reference,
        "SV-REC-2",
        "O-",
        screening_status="Pending",
        inventory_status="Testing Pending",
    )
    make_demo_unit(
        session,
        bank_id,
        don.donation_reference,
        "SV-REC-3",
        "O-",
        screening_status="Quarantined",
        inventory_status="Quarantined",
    )
    make_demo_unit(
        session,
        bank_id,
        don.donation_reference,
        "SV-REC-4",
        "O-",
        expires_in_days=-2,
        screening_status="Cleared",
        inventory_status="Expired",
    )

    recon = get_stock_reconciliation(session, blood_bank_id=bank_id)
    assert recon["total_collected"] == 4
    assert recon["current_available"] == 1
    assert recon["testing_pending"] == 1
    assert recon["quarantined"] == 1
    assert recon["total_expired"] == 1
