"""Automated tests for Module 11 — Data Quality Centre & ETL Validation."""

from __future__ import annotations

from datetime import date, timedelta
import pandas as pd

from backend.models import BloodRequest, BloodUnit
from backend.services.data_quality_service import (
    remediate_expired_released_unit,
    remediate_unreleased_quarantine_unit,
    run_data_quality_checks,
)
from etl.generate_data import generate_synthetic_dataset
from etl.validate import validate_extracted_tables
from tests.conftest import make_demo_donation, make_demo_unit


def test_data_quality_detects_anomalies_and_remediates_cleanly(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_id, "60", "O+", days_ago=20)

    # 1. Expired unit still marked Released (DQ-14)
    u_exp = make_demo_unit(session, bank_id, don.donation_reference, "SV-DQ-EXP", "O+", expires_in_days=-5)
    # 2. Uncleared unit forcibly marked Released directly in DB (DQ-06)
    u_unclr = make_demo_unit(
        session, bank_id, don.donation_reference, "SV-DQ-UNCLR", "O+",
        screening_status="Pending", inventory_status="Testing Pending",
    )
    u_unclr.inventory_status = "Released"
    # 3. Invalid processing date directly in DB (DQ-05)
    u_badproc = make_demo_unit(session, bank_id, don.donation_reference, "SV-DQ-PROC", "O+", days_ago=5, expires_in_days=20)
    u_badproc.processing_date = u_badproc.collection_date - timedelta(days=2)
    # 4. Over-fulfilled request directly in DB (DQ-11)
    bad_req = BloodRequest(
        request_reference="REQ-DQ-OVER",
        blood_bank_id=bank_id,
        hospital_id=hosp_id,
        blood_group_id=refs["blood_groups"]["O+"],
        component_id=refs["components"]["Red Blood Cells (RBC)"],
        required_quantity=2,
        fulfilled_quantity=3,
        urgency="Routine",
        request_date=date.today(),
        required_date=date.today() + timedelta(days=1),
        status="Fully Allocated",
    )
    session.add(bad_req)
    session.flush()

    dq = run_data_quality_checks(session, blood_bank_id=bank_id)
    found_codes = set(dq["issues_df"]["check_code"].tolist())
    assert "DQ-14" in found_codes
    assert "DQ-06" in found_codes
    assert "DQ-05" in found_codes
    assert "DQ-11" in found_codes
    assert dq["critical_error_count"] >= 4
    assert dq["overall_score"] < 100.0

    # Controlled audited remediations
    remediate_expired_released_unit(session, "SV-DQ-EXP", actor="pytest")
    remediate_unreleased_quarantine_unit(session, "SV-DQ-UNCLR", actor="pytest")
    session.flush()

    assert session.get(BloodUnit, u_exp.id).inventory_status == "Expired"
    assert session.get(BloodUnit, u_unclr.id).inventory_status == "Quarantined"

    dq_after = run_data_quality_checks(session, blood_bank_id=bank_id)
    after_codes = set(dq_after["issues_df"]["check_code"].tolist())
    assert "DQ-14" not in after_codes
    assert "DQ-06" not in after_codes


def test_etl_validation_catches_duplicates_and_bad_records():
    tables = generate_synthetic_dataset(seed=7, num_donors=20, num_donations=25, num_requests=20, export_csv=False)
    # Inject a duplicate unit and an invalid blood group donor
    dup_unit = tables["blood_units"].iloc[[0]].copy()
    tables["blood_units"] = pd.concat([tables["blood_units"], dup_unit], ignore_index=True)

    bad_donor = tables["donors"].iloc[[0]].copy()
    bad_donor["donor_reference"] = "DNR-BAD-BG"
    bad_donor["blood_group"] = "INVALID+"
    tables["donors"] = pd.concat([tables["donors"], bad_donor], ignore_index=True)

    accepted, report = validate_extracted_tables(tables)
    assert report.records_rejected >= 2
    assert report.duplicate_records >= 1
    assert len(report.failures) >= 2
    assert "DNR-BAD-BG" not in set(accepted["donors"]["donor_reference"])
