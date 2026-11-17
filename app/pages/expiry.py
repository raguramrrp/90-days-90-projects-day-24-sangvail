"""Module 7 — Expiry Monitoring, Configurable Windows & Controlled Discard Governance."""

from __future__ import annotations

from typing import Optional
import streamlit as st
from sqlalchemy.orm import Session

from app.components.charts import chart_bar_simple
from app.components.forms import render_validation_error
from app.components.navigation import render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from app.config import DISCARD_REASONS
from backend.services.expiry_service import record_discard_transaction, sweep_expired_units
from ml.expiry_analysis import summarize_expiry_exposure


def render_expiry_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header(
        "Expiry",
        "Expiry Monitor & Wastage Governance",
        "Component-specific expiry windows, near-expiry exposure tracking, historical wastage intelligence, and audited discard transactions.",
    )

    summary = summarize_expiry_exposure(session, blood_bank_id=blood_bank_id)
    exp_df = summary["expiry_df"]
    wast_df = summary["wastage_df"]

    render_kpi_strip(
        [
            {"label": "Expired Units (On Record)", "value": f"{summary['expired_units']:,}", "meta": "Pending disposal / expired", "tone": "critical" if summary["expired_units"] else ""},
            {"label": "Within Warning Window", "value": f"{summary['within_warning_window']:,}", "meta": "Component-configured cutoff", "tone": "warning" if summary["within_warning_window"] else ""},
            {"label": "Expiring Within 7 Days", "value": f"{summary['expiring_within_7_days']:,}", "meta": "Active Released / Reserved", "tone": "warning" if summary["expiring_within_7_days"] else ""},
            {"label": "Expiring Within 30 Days", "value": f"{summary['expiring_within_30_days']:,}", "meta": "Active Released / Reserved", "tone": ""},
            {"label": "Historical Wastage Events", "value": f"{len(wast_df):,}", "meta": "Expired + Discarded logs", "tone": ""},
        ]
    )

    tab_active, tab_intel, tab_discard = st.tabs(
        ["Expiry Watchlist", "Expiry & Wastage Intelligence", "Controlled Discard & Sweep"]
    )

    with tab_active:
        c1, c2 = st.columns([2, 2])
        with c1:
            cat_filter = st.multiselect(
                "Expiry Category",
                options=["Expired", "Critical Window", "Approaching Expiry", "Normal Shelf Life"],
                default=["Expired", "Critical Window", "Approaching Expiry"],
                key="exp_cat_f",
            )
        with c2:
            st_filter = st.multiselect(
                "Inventory Status",
                options=["Released", "Reserved", "Expired", "Testing Pending", "Quarantined"],
                default=["Released", "Reserved", "Expired"],
                key="exp_st_f",
            )

        view_df = exp_df.copy()
        if not view_df.empty:
            if cat_filter:
                view_df = view_df[view_df["expiry_category"].isin(cat_filter)]
            if st_filter:
                view_df = view_df[view_df["inventory_status"].isin(st_filter)]

        st.caption("Warning and critical windows are individually configured per blood component and blood bank in Settings.")
        render_clean_table(view_df, hide_columns=["id"], height=410)

    with tab_intel:
        r1_l, r1_r = st.columns(2)
        with r1_l:
            st.plotly_chart(
                chart_bar_simple(
                    summary["by_component_df"],
                    "component",
                    "units",
                    "Active Expiry Exposure by Component",
                    color="expiry_category",
                ),
                width="stretch",
            )
        with r1_r:
            st.plotly_chart(
                chart_bar_simple(
                    summary["by_group_df"],
                    "blood_group",
                    "units",
                    "Active Expiry Exposure by Blood Group",
                    color="expiry_category",
                ),
                width="stretch",
            )

        r2_l, r2_r = st.columns(2)
        with r2_l:
            st.plotly_chart(
                chart_bar_simple(
                    summary["monthly_wastage_df"],
                    "event_month",
                    "units",
                    "Monthly Expiry & Discard Wastage Trend",
                    color="event_type",
                ),
                width="stretch",
            )
        with r2_r:
            render_section_title("Discard & Expiry Reasons")
            render_clean_table(summary["discard_reasons_df"], height=260)

    with tab_discard:
        c_left, c_right = st.columns([1.3, 1.7])
        with c_left:
            render_section_title("Run Controlled Expiry Sweep")
            st.write(
                "Transition any past-expiry units still marked `Released`, `Testing Pending`, or `Quarantined` "
                "into `Expired` status with explicit transaction logs. No records are deleted."
            )
            if st.button("Execute Expiry Sweep", type="primary", key="btn_expiry_sweep"):
                try:
                    moved = sweep_expired_units(session, blood_bank_id=blood_bank_id, actor=actor)
                    session.commit()
                    if moved:
                        st.success(f"Transitioned {len(moved)} past-expiry unit(s) to Expired.")
                        st.rerun()
                    else:
                        st.info("No active units are past expiry date. Inventory expiry status is reconciled.")
                except Exception as exc:
                    session.rollback()
                    render_validation_error(exc)

        with c_right:
            render_section_title("Record Audited Discard Transaction")
            discardable = exp_df[exp_df["inventory_status"].isin(["Expired", "Quarantined", "Released"])] if not exp_df.empty else exp_df
            if discardable.empty:
                render_empty_state("No eligible units available for discard logging.")
            else:
                unit_map = {
                    f"{r['unit_reference']} | {r['blood_group']} {r['component']} | {r['inventory_status']} (Exp: {r['expiry_date']})": int(r["id"])
                    for _, r in discardable.head(80).iterrows()
                }
                with st.form("discard_unit_form"):
                    sel_u = st.selectbox("Select Unit to Discard *", options=list(unit_map.keys()))
                    reason_sel = st.selectbox("Discard Reason *", options=DISCARD_REASONS)
                    custom_note = st.text_input("Additional Documentation Note (Optional)")
                    confirm_disc = st.checkbox("Confirm permanent discard transaction (audit logged, never deleted)")
                    if st.form_submit_button("Record Discard", type="primary"):
                        if not confirm_disc:
                            st.warning("Please check the confirmation box before logging a discard.")
                        else:
                            full_reason = f"{reason_sel} — {custom_note}".strip(" —") if custom_note else reason_sel
                            try:
                                u_obj = record_discard_transaction(session, unit_map[sel_u], full_reason, actor=actor)
                                session.commit()
                                st.success(f"Discard transaction logged for unit {u_obj.unit_reference}.")
                                st.rerun()
                            except Exception as exc:
                                session.rollback()
                                render_validation_error(exc)
