"""Module 4 — Screening & Controlled Inventory Release Management."""

from __future__ import annotations

from typing import Optional
import streamlit as st
from sqlalchemy.orm import Session

from app.components.forms import render_validation_error
from app.components.navigation import render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from backend.schemas import ScreeningDecision
from backend.services.screening_service import list_screening_queue_df, record_screening_decision


def render_screening_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header(
        "Screening",
        "Screening & Release Control",
        "A collected unit is never automatically available. Every unit requires an authorized release decision before entering eligible stock.",
    )

    queue_df = list_screening_queue_df(session, blood_bank_id=blood_bank_id, include_completed=False)
    all_df = list_screening_queue_df(session, blood_bank_id=blood_bank_id, include_completed=True)

    pending_cnt = int(queue_df[queue_df["inventory_status"].isin(["Collected", "Testing Pending"])].shape[0]) if not queue_df.empty else 0
    quar_cnt = int(queue_df[queue_df["inventory_status"] == "Quarantined"].shape[0]) if not queue_df.empty else 0
    overdue_cnt = int(queue_df[queue_df["days_since_collection"] > 2].shape[0]) if not queue_df.empty else 0
    cleared_cnt = int(all_df[all_df["screening_status"] == "Cleared"].shape[0]) if not all_df.empty else 0
    rejected_cnt = int(all_df[all_df["inventory_status"] == "Rejected"].shape[0]) if not all_df.empty else 0

    render_kpi_strip(
        [
            {"label": "Pending Screening", "value": f"{pending_cnt:,}", "meta": "Collected / Testing Pending", "tone": "warning" if pending_cnt else ""},
            {"label": "Pending > 2 Days", "value": f"{overdue_cnt:,}", "meta": "Exceeding target SLA", "tone": "critical" if overdue_cnt else ""},
            {"label": "Quarantined Units", "value": f"{quar_cnt:,}", "meta": "Held off eligible stock", "tone": "warning" if quar_cnt else ""},
            {"label": "Cleared", "value": f"{cleared_cnt:,}", "meta": "Cumulative cleared records", "tone": "accent"},
            {"label": "Rejected Units", "value": f"{rejected_cnt:,}", "meta": "Blocked from release/issue", "tone": ""},
        ]
    )



    tab_queue, tab_history = st.tabs(["Active Screening Queue", "Full Screening Audit History"])

    with tab_queue:
        col_tbl, col_act = st.columns([2.2, 1.2])
        with col_tbl:
            render_section_title("Units Awaiting Release / Quarantine Disposition")
            render_clean_table(queue_df, hide_columns=["unit_id", "reviewed_at", "notes"], height=400)

        with col_act:
            render_section_title("Record Release / Screening Decision")
            if queue_df.empty:
                render_empty_state("All units have completed screening disposition.")
            else:
                unit_options = {
                    f"{r['unit_reference']} | {r['blood_group']} {r['component']} ({r['inventory_status']})": int(r["unit_id"])
                    for _, r in queue_df.iterrows()
                }
                with st.form("screening_decision_form"):
                    sel_unit = st.selectbox("Target Blood Unit *", options=list(unit_options.keys()))
                    action_choice = st.selectbox(
                        "Authorized Disposition *",
                        options=[
                            "Release to Eligible Inventory (Cleared)",
                            "Place on Quarantine Hold (Quarantined)",
                            "Reject Unit Permanently (Rejected)",
                            "Keep Testing Pending (In Progress)",
                        ],
                    )
                    res_ref = st.text_input("Screening Result Reference *", value="SCR-REVIEW")
                    note = st.text_area("Review Notes", placeholder="Enter administrative review note", height=70)
                    confirm_btn = st.form_submit_button("Apply Screening Decision", type="primary", width="stretch")

                    if confirm_btn:
                        mapping = {
                            "Release to Eligible Inventory (Cleared)": ("Cleared", "Released"),
                            "Place on Quarantine Hold (Quarantined)": ("Quarantined", "Quarantined"),
                            "Reject Unit Permanently (Rejected)": ("Rejected", "Rejected"),
                            "Keep Testing Pending (In Progress)": ("In Progress", "Testing Pending"),
                        }
                        scr_st, inv_st = mapping[action_choice]
                        try:
                            decision = ScreeningDecision(
                                unit_id=unit_options[sel_unit],
                                new_screening_status=scr_st,
                                target_inventory_status=inv_st,
                                result_reference=res_ref,
                                reference_note=note,
                                reviewed_by=actor,
                            )
                            rec = record_screening_decision(session, decision, actor=actor)
                            session.commit()
                            st.success(f"Recorded {rec.screening_reference}: unit moved to '{inv_st}'.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

    with tab_history:
        render_clean_table(all_df.head(300), hide_columns=["unit_id"], height=430)
