"""Automated tests for Network Hubs, Surgery Pre-Reservation, Cold-Chain Transport & Billing."""

from __future__ import annotations

from datetime import date, timedelta
import pytest

from backend.models import BloodUnit
from backend.services.network_dispatch_service import (
    advance_dispatch_status,
    arrange_transport_dispatch,
    cancel_surgical_booking,
    complete_surgical_booking,
    create_surgical_booking,
    estimate_service_charges,
    find_nearest_storage_hubs,
    generate_payment_receipt_pdf,
    record_service_payment,
    request_and_reserve_from_hub,
)
from backend.validators.integrity import DomainValidationError
from tests.conftest import make_demo_donation, make_demo_unit


def test_nearest_storage_hubs_and_rapid_reserve(db_session):
    session, refs, _ = db_session
    bank_ids = list(refs["blood_banks"].values())
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_ids[0], "80", "O+", days_ago=4)
    make_demo_unit(session, bank_ids[0], don.donation_reference, "SV-NET-01", "O+", expires_in_days=20)
    make_demo_unit(session, bank_ids[0], don.donation_reference, "SV-NET-02", "O+", expires_in_days=25)
    session.flush()

    hubs_df = find_nearest_storage_hubs(session, "O+", "Red Blood Cells (RBC)", quantity_needed=2, hospital_id=hosp_id)
    assert len(hubs_df) == len(bank_ids)
    top_hub = hubs_df.iloc[0]
    assert top_hub["blood_bank_id"] == bank_ids[0]
    assert top_hub["can_fulfill_full"]
    assert top_hub["distance_km"] >= 0

    res = request_and_reserve_from_hub(
        session,
        hospital_id=hosp_id,
        blood_bank_id=bank_ids[0],
        blood_group="O+",
        component_name="Red Blood Cells (RBC)",
        quantity=2,
        auto_reserve=True,
        human_approval_confirmed=True,
    )
    assert res["allocated_count"] == 2
    assert res["status"] == "Fully Allocated"


def test_surgical_booking_respects_surgery_date_expiry_and_rollback(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_id, "81", "A+", days_ago=3)

    # Unit expiring in 2 days cannot serve a surgery 5 days from now
    u_short = make_demo_unit(session, bank_id, don.donation_reference, "SV-SURG-SHORT", "A+", expires_in_days=2)
    u_long = make_demo_unit(session, bank_id, don.donation_reference, "SV-SURG-LONG", "A+", expires_in_days=18)
    session.flush()

    surgery_dt = date.today() + timedelta(days=5)
    # Asking for 2 units must fail because only 1 unit stays valid until surgery_dt
    with pytest.raises(DomainValidationError, match="remain valid through surgery date"):
        create_surgical_booking(
            session,
            hospital_id=hosp_id,
            blood_bank_id=bank_id,
            blood_group="A+",
            component_name="Red Blood Cells (RBC)",
            quantity=2,
            procedure_category="Cardiac Bypass / Valve Surgery",
            surgery_date=surgery_dt,
        )

    # Asking for 1 unit must pick SV-SURG-LONG (never SV-SURG-SHORT)
    bk = create_surgical_booking(
        session,
        hospital_id=hosp_id,
        blood_bank_id=bank_id,
        blood_group="A+",
        component_name="Red Blood Cells (RBC)",
        quantity=1,
        procedure_category="Cardiac Bypass / Valve Surgery",
        surgery_date=surgery_dt,
    )
    assert bk["reserved_units"] == ["SV-SURG-LONG"]
    assert session.get(BloodUnit, u_long.id).inventory_status == "Reserved"
    assert session.get(BloodUnit, u_short.id).inventory_status == "Released"

    # Releasing surgical hold restores SV-SURG-LONG to Released
    cancel_surgical_booking(session, bk["booking_id"], "Patient rescheduled")
    assert session.get(BloodUnit, u_long.id).inventory_status == "Released"


def test_transport_dispatch_and_service_payment_pdf(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))
    don = make_demo_donation(session, bank_id, "82", "B+", days_ago=5)
    make_demo_unit(session, bank_id, don.donation_reference, "SV-TRN-01", "B+", expires_in_days=22)
    session.flush()

    bk = create_surgical_booking(
        session,
        hospital_id=hosp_id,
        blood_bank_id=bank_id,
        blood_group="B+",
        component_name="Red Blood Cells (RBC)",
        quantity=1,
        procedure_category="Orthopedic Joint Replacement",
        surgery_date=date.today() + timedelta(days=2),
    )

    disp = arrange_transport_dispatch(
        session,
        request_id=bk["request_id"],
        transport_mode="Emergency Cold-Chain Ambulance",
        vehicle_reference="AMB-201",
        courier_name="Logistics Officer 02",
        container_id="COOLBOX-09",
    )
    assert disp.status == "Scheduled"
    assert disp.required_temp_range == "2°C to 6°C"

    est = estimate_service_charges(session, request_id=bk["request_id"], dispatch_id=disp.id)
    assert est["component_service_fee"] == 1100.0
    assert est["transport_fee"] > 0
    assert est["total_amount"] == est["component_service_fee"] + est["transport_fee"]

    pay = record_service_payment(
        session,
        request_id=bk["request_id"],
        payment_method="UPI Instant Settlement (Simulated)",
        dispatch_id=disp.id,
    )
    assert pay.payment_status == "Paid"
    pdf_bytes = generate_payment_receipt_pdf(session, pay.id)
    assert pdf_bytes.startswith(b"%PDF")

    advance_dispatch_status(session, disp.id, "In Transit")
    advance_dispatch_status(session, disp.id, "Delivered")
    assert disp.status == "Delivered"
    assert disp.delivered_at is not None
