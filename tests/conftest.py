"""Pytest fixtures providing isolated temporary SQLite databases for SANGVAIL."""

from __future__ import annotations

from datetime import date, timedelta
import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.database import create_db_engine, get_session_factory, init_db
from backend.schemas import BloodUnitCreate, DonationCreate, DonorCreate
from backend.services.donation_service import create_donation, create_donor
from backend.services.inventory_service import create_blood_unit
from etl.load import seed_master_reference_data


@pytest.fixture()
def db_session(tmp_path):
    db_file = tmp_path / "test_sangvail.db"
    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    init_db(engine)
    SessionLocal = get_session_factory(engine)
    session = SessionLocal()
    refs = seed_master_reference_data(session)
    session.commit()
    try:
        yield session, refs, engine
    finally:
        session.close()
        engine.dispose()


def make_demo_donation(session, bank_id: int, suffix: str = "01", blood_group: str = "O+", days_ago: int = 5):
    donor_ref = f"DNR-T{suffix}"
    don_ref = f"DN-T{suffix}"
    create_donor(
        session,
        DonorCreate(
            donor_reference=donor_ref,
            full_name=f"Test Donor {suffix}",
            age_band="26-35",
            blood_group=blood_group,
            contact=f"test.{suffix}@example.invalid",
            registration_date=date.today() - timedelta(days=30),
        ),
        actor="pytest",
    )
    donation = create_donation(
        session,
        DonationCreate(
            donation_reference=don_ref,
            donor_reference=donor_ref,
            blood_bank_id=bank_id,
            donation_date=date.today() - timedelta(days=days_ago),
            collection_location="Test Suite",
            collection_type="Whole Blood Collection",
            collection_status="Collected",
            collected_quantity=450,
            collection_staff="Tech-Test",
        ),
        actor="pytest",
    )
    session.flush()
    return donation


def make_demo_unit(
    session,
    bank_id: int,
    donation_reference: str,
    unit_ref: str,
    blood_group: str = "O+",
    component_name: str = "Red Blood Cells (RBC)",
    days_ago: int = 3,
    expires_in_days: int = 20,
    screening_status: str = "Cleared",
    inventory_status: str = "Released",
):
    col_dt = date.today() - timedelta(days=days_ago)
    exp_dt = date.today() + timedelta(days=expires_in_days)
    if exp_dt <= col_dt:
        col_dt = exp_dt - timedelta(days=10)
    unit = create_blood_unit(
        session,
        BloodUnitCreate(
            unit_reference=unit_ref,
            donation_reference=donation_reference,
            blood_bank_id=bank_id,
            blood_group=blood_group,
            component_name=component_name,
            collection_date=col_dt,
            processing_date=col_dt,
            expiry_date=exp_dt,
            storage_location="Cold Room A — Rack 1 (2-6°C)",
            screening_status=screening_status,
            inventory_status=inventory_status,
        ),
        actor="pytest",
    )
    session.flush()
    return unit
