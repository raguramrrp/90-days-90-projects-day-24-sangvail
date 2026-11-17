"""SANGVAIL — Blood Bank Inventory, Operations & Demand Intelligence Platform."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

from app.components.navigation import (
    init_session_state,
    inject_theme_css,
    render_footer_disclaimer,
    render_login_screen,
    render_patient_navigation,
    render_top_navigation,
)
from app.config import APP_FULL_NAME, APP_NAME
from app.pages.data_quality import render_data_quality_page
from app.pages.demand_intelligence import render_demand_intelligence_page
from app.pages.donations import render_donations_page
from app.pages.expiry import render_expiry_page
from app.pages.forecasting import render_forecasting_page
from app.pages.inventory import render_inventory_page
from app.pages.network_dispatch import render_network_dispatch_page
from app.pages.overview import render_overview_page
from app.pages.patient_portal import render_patient_portal_page
from app.pages.reports import render_reports_page
from app.pages.requests import render_requests_page
from app.pages.screening import render_screening_page
from app.pages.settings import render_settings_page
from backend.database import get_session_factory, init_db
from database.seed_data import seed_database


@st.cache_resource
def bootstrap_database() -> bool:
    """Initialize schema and ensure synthetic demonstration records exist on first launch."""
    init_db()
    seed_database(export_csv=True)
    return True


def main() -> None:
    st.set_page_config(
        page_title=f"{APP_NAME} — {APP_FULL_NAME}",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_theme_css()
    init_session_state()
    bootstrap_database()

    SessionFactory = get_session_factory()
    session = SessionFactory()
    try:
        if not st.session_state.get("authenticated", False):
            render_login_screen(session)
            return

        current_user = st.session_state.get("current_user") or {
            "username": "admin",
            "display_name": "Operations Administrator",
            "role": "Administrator",
        }
        if current_user.get("role") == "Patient":
            active_pt_tab = render_patient_navigation(current_user)
            render_patient_portal_page(session, current_user, active_pt_tab)
            return

        actor = current_user.get("username", "admin")
        selected_bank_id = render_top_navigation(session)
        page = st.session_state.get("active_page", "Overview")

        if page == "Overview":
            render_overview_page(session, selected_bank_id)
        elif page == "Inventory":
            render_inventory_page(session, selected_bank_id, actor=actor)
        elif page == "Donations":
            render_donations_page(session, selected_bank_id, actor=actor)
        elif page == "Screening":
            render_screening_page(session, selected_bank_id, actor=actor)
        elif page == "Requests":
            render_requests_page(session, selected_bank_id, actor=actor)
        elif page == "Network":
            render_network_dispatch_page(session, selected_bank_id, actor=actor)
        elif page == "Expiry":
            render_expiry_page(session, selected_bank_id, actor=actor)
        elif page == "Intelligence":
            render_demand_intelligence_page(session, selected_bank_id)
        elif page == "Forecasting":
            render_forecasting_page(session, selected_bank_id)
        elif page == "Data Quality":
            render_data_quality_page(session, selected_bank_id, actor=actor)
        elif page == "Reports":
            render_reports_page(session, selected_bank_id)
        elif page == "Settings":
            render_settings_page(session, selected_bank_id, actor=actor)
        else:
            render_overview_page(session, selected_bank_id)
    finally:
        session.close()


if __name__ == "__main__":
    main()
