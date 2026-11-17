"""Automated tests for Patient / User Portal registration, auth, requests, and UI views."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

from backend.auth import authenticate_user, register_patient_user
from backend.schemas import BloodRequestCreate
from backend.services.request_service import create_blood_request, list_requests_df


def test_patient_registration_validation_and_login(db_session):
    session, _, _ = db_session

    # Default patient account seeded cleanly
    default_pt = authenticate_user(session, "patient", "patient123")
    assert default_pt is not None
    assert default_pt.role == "Patient"

    # Reject short password
    with pytest.raises(ValueError, match="at least 6 characters"):
        register_patient_user(session, "newuser", "123", "Test User")

    # Create valid patient account
    u = register_patient_user(session, "ananya.k", "securePass1", "Ananya K")
    assert u.role == "Patient"
    assert authenticate_user(session, "ananya.k", "securePass1") is not None

    # Reject duplicate username
    with pytest.raises(ValueError, match="already registered"):
        register_patient_user(session, "ananya.k", "anotherPass", "Ananya Duplicate")


def test_patient_requests_are_scoped_to_requester(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    hosp_id = next(iter(refs["hospitals"].values()))

    register_patient_user(session, "user_a", "pass1234", "User A")
    register_patient_user(session, "user_b", "pass1234", "User B")

    create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-PT-A1",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="O+",
            component_name="Red Blood Cells (RBC)",
            required_quantity=2,
            urgency="Priority",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
        actor="user_a",
    )
    create_blood_request(
        session,
        BloodRequestCreate(
            request_reference="REQ-PT-B1",
            blood_bank_id=bank_id,
            hospital_id=hosp_id,
            blood_group="A+",
            component_name="Platelets",
            required_quantity=1,
            urgency="Routine",
            request_date=date.today(),
            required_date=date.today() + timedelta(days=1),
        ),
        actor="user_b",
    )
    session.flush()

    a_reqs = list_requests_df(session, created_by="user_a")
    assert list(a_reqs["request_reference"]) == ["REQ-PT-A1"]
    b_reqs = list_requests_df(session, created_by="user_b")
    assert list(b_reqs["request_reference"]) == ["REQ-PT-B1"]


def test_patient_portal_all_five_views_render_cleanly():
    main_path = Path(__file__).resolve().parent.parent / "app" / "main.py"
    at = AppTest.from_file(str(main_path), default_timeout=30)
    at.run()
    assert not at.exception

    at.session_state["authenticated"] = True
    at.session_state["current_user"] = {
        "id": 2,
        "username": "patient",
        "display_name": "Patient Portal User",
        "role": "Patient",
    }

    for tab in ["Availability", "New Request", "Surgery Booking", "My Requests", "Payments"]:
        at.session_state["patient_active_tab"] = tab
        at.run()
        assert not at.exception, f"Exception on Patient Portal tab '{tab}': {at.exception}"
        for md in at.markdown:
            assert "<div class=" not in md.value
            assert "<span class=" not in md.value
