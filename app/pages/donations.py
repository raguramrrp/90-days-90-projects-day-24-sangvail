"""Module 3 — Donation Register, Synthetic Donors & Component Separation."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from app.components.charts import chart_bar_simple, chart_line_simple
from app.components.forms import render_validation_error
from app.components.navigation import render_page_header
from app.components.tables import render_clean_table, render_kpi_strip, render_section_title
from app.config import BLOOD_GROUP_NAMES, DONATION_STATUSES
from backend.repositories.master_repo import get_blood_banks, get_components
from backend.schemas import DonationCreate, DonorCreate
from backend.services.donation_service import (
    create_donation,
    create_donor,
    list_donations_df,
    list_donors_df,
    produce_component_units_from_donation,
    update_donation_status,
)
from backend.services.settings_service import get_storage_locations


def render_donations_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header(
        "Donations",
        "Donation Management",
        "Track synthetic donor collections, processing workflows, component traceability, and intake trends.",
    )

    f1, f2, f3 = st.columns([1.4, 1.4, 2.2])
    with f1:
        start_dt = st.date_input("From Date", value=date.today() - timedelta(days=365), key="don_start")
    with f2:
        end_dt = st.date_input("To Date", value=date.today(), key="don_end")
    with f3:
        bg_sel = st.multiselect("Blood Group", options=BLOOD_GROUP_NAMES, default=[], key="don_bg_f", placeholder="All blood groups")

    don_df = list_donations_df(
        session,
        blood_bank_id=blood_bank_id,
        blood_groups=bg_sel or None,
        start_date=start_dt,
        end_date=end_dt,
    )

    total_dons = len(don_df)
    completed = int((don_df["collection_status"] == "Completed").sum()) if not don_df.empty else 0
    rejected = int((don_df["collection_status"] == "Rejected").sum()) if not don_df.empty else 0
    avg_vol = f"{don_df['collected_quantity'].mean():.0f} mL" if not don_df.empty else "0 mL"
    produced_total = int(don_df["units_produced"].sum()) if not don_df.empty else 0

    render_kpi_strip(
        [
            {"label": "Total Donations", "value": f"{total_dons:,}", "meta": "Selected period", "tone": "accent"},
            {"label": "Completed Collections", "value": f"{completed:,}", "meta": f"{(completed / max(1, total_dons) * 100):.1f}% success rate", "tone": ""},
            {"label": "Rejected Collections", "value": f"{rejected:,}", "meta": "Deferred / insufficient draw", "tone": "warning" if rejected > 0 else ""},
            {"label": "Average Collection Volume", "value": avg_vol, "meta": "Across logged draws", "tone": ""},
            {"label": "Component Units Produced", "value": f"{produced_total:,}", "meta": "Traceable unit records", "tone": "accent"},
        ]
    )

    tab_reg, tab_analytics, tab_workflow, tab_donors = st.tabs(
        ["Donation Register", "Donation Analytics", "Record & Process Donation", "Synthetic Donor Registry"]
    )

    with tab_reg:
        render_clean_table(don_df, hide_columns=["id"], height=400)

    with tab_analytics:
        if don_df.empty:
            st.info("No donation records found for the selected filter window.")
        else:
            df_a = don_df.copy()
            df_a["month"] = pd.to_datetime(df_a["donation_date"]).dt.strftime("%Y-%m")
            c1, c2 = st.columns(2)
            with c1:
                m_df = df_a.groupby("month", as_index=False)["id"].count().rename(columns={"id": "donations"}).sort_values("month")
                st.plotly_chart(chart_line_simple(m_df, "month", "donations", "Monthly Donation Collection Trend", y_title="Donations"), width="stretch")
            with c2:
                bg_df = df_a.groupby("blood_group", as_index=False)["id"].count().rename(columns={"id": "donations"})
                st.plotly_chart(chart_bar_simple(bg_df, "blood_group", "donations", "Donations by Blood Group"), width="stretch")

            c3, c4 = st.columns(2)
            with c3:
                sr_df = df_a.groupby(["month", "collection_status"], as_index=False)["id"].count().rename(columns={"id": "donations"})
                st.plotly_chart(chart_bar_simple(sr_df, "month", "donations", "Successful vs. Rejected Collections", color="collection_status"), width="stretch")
            with c4:
                ct_df = df_a.groupby("collection_type", as_index=False)["id"].count().rename(columns={"id": "donations"})
                st.plotly_chart(chart_bar_simple(ct_df, "collection_type", "donations", "Donations by Collection Type"), width="stretch")

    with tab_workflow:
        col_new, col_proc = st.columns(2)
        donors_df = list_donors_df(session)
        banks = get_blood_banks(session)
        bank_map = {b.bank_name: b.id for b in banks}

        with col_new:
            render_section_title("Log New Donation")
            with st.form("new_donation_form", clear_on_submit=True):
                d_ref = st.text_input("Donation ID *", placeholder="DN-90001")
                donor_opts = donors_df["donor_reference"].tolist() if not donors_df.empty else []
                dn_ref = st.selectbox("Donor Reference *", options=donor_opts)
                b_name = st.selectbox("Blood Bank *", options=list(bank_map.keys()))
                d_dt = st.date_input("Donation Date *", value=date.today())
                c_loc = st.text_input("Collection Location *", value="Central Donor Suite A")
                c_type = st.selectbox("Donation Type", ["Whole Blood Collection", "Apheresis Platelets", "Double RBC Apheresis"])
                c_qty = st.number_input("Collected Volume (mL)", min_value=100, max_value=900, value=450, step=50)
                c_staff = st.text_input("Responsible Collection Staff *", value="Tech-01")
                c_status = st.selectbox("Initial Status", options=DONATION_STATUSES, index=1)
                c_notes = st.text_area("Notes", height=60)
                if st.form_submit_button("Save Donation", type="primary"):
                    try:
                        payload = DonationCreate(
                            donation_reference=d_ref,
                            donor_reference=dn_ref,
                            blood_bank_id=bank_map[b_name],
                            donation_date=d_dt,
                            collection_location=c_loc,
                            collection_type=c_type,
                            collection_status=c_status,
                            collected_quantity=int(c_qty),
                            collection_staff=c_staff,
                            notes=c_notes,
                        )
                        created = create_donation(session, payload, actor=actor)
                        session.commit()
                        st.success(f"Donation {created.donation_reference} logged.")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

        with col_proc:
            render_section_title("Produce Component Units from Donation")
            eligible_dons = don_df[don_df["collection_status"].isin(["Collected", "Processing", "Completed"])] if not don_df.empty else pd.DataFrame()
            if eligible_dons.empty:
                st.info("No eligible donations available for component production.")
            else:
                don_id_map = {
                    f"{r['donation_reference']} ({r['blood_group']}, {r['donation_date']}, {r['collection_status']})": int(r["id"])
                    for _, r in eligible_dons.head(40).iterrows()
                }
                comps = [c.component_name for c in get_components(session, only_enabled=True)]
                locs = get_storage_locations(session)

                with st.form("produce_comp_form"):
                    chosen_don = st.selectbox("Select Donation", options=list(don_id_map.keys()))
                    chosen_comps = st.multiselect("Components to Produce", options=comps, default=[comps[0]] if comps else [])
                    chosen_loc = st.selectbox("Target Storage Location", options=locs)
                    proc_date = st.date_input("Processing Date", value=date.today())
                    if st.form_submit_button("Produce Traceable Units", type="primary"):
                        try:
                            units = produce_component_units_from_donation(
                                session,
                                donation_id=don_id_map[chosen_don],
                                component_names=chosen_comps,
                                storage_location=chosen_loc,
                                processing_date=proc_date,
                                actor=actor,
                            )
                            session.commit()
                            st.success(f"Produced {len(units)} unit(s): {', '.join(u.unit_reference for u in units)}.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

            render_section_title("Update Donation Status")
            open_dons = don_df[don_df["collection_status"].isin(["Registered", "Collected", "Processing"])] if not don_df.empty else pd.DataFrame()
            if not open_dons.empty:
                open_map = {f"{r['donation_reference']} ({r['collection_status']})": int(r["id"]) for _, r in open_dons.iterrows()}
                with st.form("update_don_status_form"):
                    sel_d = st.selectbox("In-Progress Donation", options=list(open_map.keys()))
                    new_st = st.selectbox("Target Status", options=["Collected", "Processing", "Completed", "Rejected"])
                    st_note = st.text_input("Status Note")
                    if st.form_submit_button("Transition Status"):
                        try:
                            update_donation_status(session, open_map[sel_d], new_st, actor=actor, notes=st_note)
                            session.commit()
                            st.success("Donation status updated.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

    with tab_donors:
        st.caption("Registered donor profiles.")
        c_tbl, c_form = st.columns([2.2, 1.2])
        with c_tbl:
            render_clean_table(donors_df, hide_columns=["id"], height=380)
        with c_form:
            render_section_title("Register Synthetic Donor")
            with st.form("add_donor_form", clear_on_submit=True):
                dnr_ref = st.text_input("Donor Ref *", placeholder="DNR-9001")
                dnr_name = st.text_input("Donor Name *", placeholder="Donor #9001")
                dnr_age = st.selectbox("Age Band", ["18-25", "26-35", "36-45", "46-55", "56-65"])
                dnr_bg = st.selectbox("Blood Group", BLOOD_GROUP_NAMES)
                dnr_contact = st.text_input("Contact *", value="donor.9001@example.invalid")
                dnr_reg = st.date_input("Registration Date", value=date.today())
                if st.form_submit_button("Register Donor", type="primary"):
                    try:
                        payload = DonorCreate(
                            donor_reference=dnr_ref,
                            full_name=dnr_name,
                            age_band=dnr_age,
                            blood_group=dnr_bg,
                            contact=dnr_contact,
                            registration_date=dnr_reg,
                        )
                        d_obj = create_donor(session, payload, actor=actor)
                        session.commit()
                        st.success(f"Synthetic donor {d_obj.donor_reference} registered.")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)
