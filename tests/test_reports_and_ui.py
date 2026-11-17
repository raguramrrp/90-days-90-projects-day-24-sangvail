"""Automated tests for Reports (CSV/Excel/PDF), Seeded DB Integrity, and Streamlit UI smoke flow."""

from __future__ import annotations

from pathlib import Path
from streamlit.testing.v1 import AppTest

from backend.database import get_db_session
from backend.services.data_quality_service import run_data_quality_checks
from backend.services.report_service import (
    REPORT_CATALOG,
    build_report_dataset,
    dataframe_to_csv_bytes,
    dataframe_to_excel_bytes,
    generate_pdf_report_bytes,
)
from database.seed_data import seed_database


def test_all_eight_reports_generate_csv_excel_and_pdf():
    seed_database(export_csv=False)
    with get_db_session() as session:
        # Also verify the live seeded demo database scores 100% on Data Quality checks
        dq = run_data_quality_checks(session)
        assert dq["critical_error_count"] == 0, f"Seeded DB has critical DQ issues: {dq['issues_df']}"

        for key in REPORT_CATALOG:
            title, df, metrics = build_report_dataset(session, report_key=key)
            assert title
            csv_b = dataframe_to_csv_bytes(df)
            xlsx_b = dataframe_to_excel_bytes(df, sheet_name=key)
            pdf_b = generate_pdf_report_bytes(title=title, df=df, metrics=metrics)

            assert len(csv_b) > 0
            assert len(xlsx_b) > 100
            assert pdf_b.startswith(b"%PDF")

            # Verify donor personal names & contact are excluded from donation export by default
            if key == "donation_collection" and not df.empty:
                assert "donor_name" not in df.columns
                assert "full_name" not in df.columns
                assert "contact" not in df.columns


def test_streamlit_ui_login_and_page_navigation():
    main_path = Path(__file__).resolve().parent.parent / "app" / "main.py"
    at = AppTest.from_file(str(main_path), default_timeout=30)
    at.run()
    assert not at.exception
    # Ensure no raw HTML leaked into markdown blocks on login screen
    for md in at.markdown:
        assert "<div class=" not in md.value
        assert "<span class=" not in md.value

    at.session_state["authenticated"] = True
    at.session_state["current_user"] = {
        "id": 1,
        "username": "admin",
        "display_name": "Operations Administrator",
        "role": "Administrator",
    }

    for page_key in [
        "Overview",
        "Inventory",
        "Donations",
        "Screening",
        "Requests",
        "Network",
        "Expiry",
        "Intelligence",
        "Forecasting",
        "Data Quality",
        "Reports",
        "Settings",
    ]:
        at.session_state["active_page"] = page_key
        at.run()
        assert not at.exception, f"Unhandled exception on page '{page_key}': {at.exception}"
        for md in at.markdown:
            assert "<div class=" not in md.value, f"Raw HTML leaked into markdown on '{page_key}'"
            assert "<span class=" not in md.value, f"Raw HTML leaked into markdown on '{page_key}'"
