"""Module 2 — Unit-Level Inventory Management & Stock Reconciliation."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.components.filters import render_blood_group_component_filters
from app.components.forms import render_validation_error
from app.components.navigation import render_page_header
from app.components.tables import render_clean_table, render_kpi_strip, render_section_title
from app.config import BLOOD_GROUP_NAMES, INVENTORY_STATUSES, SCREENING_STATUSES
from backend.models import Donation
from backend.repositories.master_repo import get_blood_banks, get_components
from backend.schemas import BloodUnitCreate
from backend.services.inventory_service import (
    create_blood_unit,
    get_stock_by_group_and_component,
    get_stock_reconciliation,
    list_inventory_df,
)
from backend.services.settings_service import get_storage_locations


def render_inventory_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header(
        "Inventory",
        "Blood Unit Inventory",
        "Unit-level blood custody ledger. Only cleared, released, non-expired units are counted as eligible available stock.",
    )

    recon = get_stock_reconciliation(session, blood_bank_id=blood_bank_id)
    render_kpi_strip(
        [
            {"label": "Eligible Available", "value": f"{recon['current_available']:,}", "meta": "Released & non-expired", "tone": "accent"},
            {"label": "Reserved", "value": f"{recon['total_reserved']:,}", "meta": "Excluded from free stock", "tone": ""},
            {"label": "Pending / Quarantined", "value": f"{recon['collected_raw'] + recon['testing_pending'] + recon['quarantined']:,}", "meta": f"{recon['quarantined']} quarantined", "tone": "warning"},
            {"label": "Issued (Cumulative)", "value": f"{recon['total_issued']:,}", "meta": "Completed handovers", "tone": ""},
            {"label": "Expired / Discarded", "value": f"{recon['total_expired'] + recon['total_discarded']:,}", "meta": f"{recon['total_expired']} expired, {recon['total_discarded']} discarded", "tone": "critical" if recon["total_expired"] > 0 else ""},
            {"label": "Total Collected Units", "value": f"{recon['total_collected']:,}", "meta": "Reconciled unit records", "tone": ""},
        ]
    )

    tab_ledger, tab_matrix, tab_add = st.tabs(["Unit Ledger", "Availability by Group & Component", "Register Blood Unit"])

    comps = get_components(session, only_enabled=False)
    comp_names = [c.component_name for c in comps]
    storage_locs = get_storage_locations(session)

    with tab_ledger:
        f1, f2 = st.columns([2.2, 2.8])
        with f1:
            search_uid = st.text_input("Search Unit ID", placeholder="e.g. SV-00412", key="inv_search_uid")
        with f2:
            selected_bg, selected_comp = render_blood_group_component_filters(comp_names, "inv")

        f3, f4, f5 = st.columns([1.8, 1.8, 1.4])
        with f3:
            selected_statuses = st.multiselect(
                "Inventory Status",
                options=INVENTORY_STATUSES,
                default=["Released", "Reserved", "Testing Pending", "Quarantined"],
                key="inv_status_filter",
            )
        with f4:
            selected_loc = st.selectbox("Storage Location", options=["All"] + storage_locs, key="inv_loc_filter")
        with f5:
            expiry_window = st.selectbox(
                "Expiry Filter",
                options=["All", "Expiring in 7 days", "Expiring in 30 days", "Expired only"],
                key="inv_exp_filter",
            )

        today = date.today()
        exp_start, exp_end = None, None
        if expiry_window == "Expiring in 7 days":
            exp_start, exp_end = today, today + timedelta(days=7)
        elif expiry_window == "Expiring in 30 days":
            exp_start, exp_end = today, today + timedelta(days=30)
        elif expiry_window == "Expired only":
            exp_end = today - timedelta(days=1)

        inv_df = list_inventory_df(
            session,
            blood_bank_id=blood_bank_id,
            blood_groups=selected_bg or None,
            components=selected_comp or None,
            statuses=selected_statuses or None,
            storage_location=selected_loc,
            search_unit_id=search_uid,
            expiry_start=exp_start,
            expiry_end=exp_end,
        )
        st.caption(f"Showing {len(inv_df):,} unit record(s) matching current filters.")
        render_clean_table(inv_df, hide_columns=["id", "is_eligible_available"], height=430)

    with tab_matrix:
        render_section_title("Reconciled Stock Matrix (Database-Derived)")
        st.caption(
            "Blood group labels are displayed strictly for inventory classification. "
            "Do not infer universal donor or recipient clinical compatibility from ABO/Rh labels alone."
        )
        mat_df = get_stock_by_group_and_component(session, blood_bank_id=blood_bank_id)
        render_clean_table(mat_df, height=420)

    with tab_add:
        render_section_title("Register Individual Blood Unit")
        banks = get_blood_banks(session)
        enabled_comps = [c for c in comps if c.enabled]
        recent_donations = session.scalars(
            select(Donation)
            .where(Donation.collection_status != "Rejected")
            .order_by(Donation.donation_date.desc(), Donation.id.desc())
            .limit(100)
        ).all()

        if not recent_donations:
            st.warning("Create a valid donation record before registering individual blood units.")
            return

        comp_by_name = {c.component_name: c for c in enabled_comps}
        don_refs = [d.donation_reference for d in recent_donations]

        with st.form("add_unit_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                unit_ref = st.text_input("Unit ID *", placeholder="SV-90001")
                don_ref = st.selectbox("Donation Reference *", options=don_refs)
                bg_val = st.selectbox("Blood Group *", options=BLOOD_GROUP_NAMES)
            with c2:
                comp_val = st.selectbox("Component *", options=[c.component_name for c in enabled_comps])
                bank_map = {b.bank_name: b.id for b in banks}
                bank_val = st.selectbox("Blood Bank *", options=list(bank_map.keys()))
                loc_val = st.selectbox("Storage Location *", options=storage_locs)
            with c3:
                col_dt = st.date_input("Collection Date *", value=date.today())
                proc_dt = st.date_input("Processing Date", value=date.today())
                default_exp = date.today() + timedelta(days=comp_by_name[comp_val].default_shelf_life_days)
                exp_dt = st.date_input("Expiry Date *", value=default_exp)

            c4, c5 = st.columns(2)
            with c4:
                scr_val = st.selectbox("Initial Screening Status", options=SCREENING_STATUSES, index=0)
            with c5:
                inv_val = st.selectbox(
                    "Initial Inventory Status",
                    options=["Collected", "Testing Pending", "Quarantined", "Released"],
                    index=1,
                )

            submitted = st.form_submit_button("Register Unit", type="primary")
            if submitted:
                try:
                    payload = BloodUnitCreate(
                        unit_reference=unit_ref,
                        donation_reference=don_ref,
                        blood_bank_id=bank_map[bank_val],
                        blood_group=bg_val,
                        component_name=comp_val,
                        collection_date=col_dt,
                        processing_date=proc_dt,
                        expiry_date=exp_dt,
                        storage_location=loc_val,
                        screening_status=scr_val,
                        inventory_status=inv_val,
                    )
                    unit = create_blood_unit(session, payload, actor=actor)
                    session.commit()
                    st.success(f"Unit {unit.unit_reference} registered and logged in inventory transactions.")
                    st.rerun()
                except Exception as exc:
                    session.rollback()
                    render_validation_error(exc)
