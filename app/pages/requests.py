"""Modules 5 & 6 — Hospital Blood Requests & FEFO Allocation Engine."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from app.components.filters import render_blood_group_component_filters
from app.components.forms import render_validation_error
from app.components.navigation import render_html, render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from app.config import BLOOD_GROUP_NAMES, REQUEST_STATUSES, REQUEST_URGENCIES
from backend.repositories.master_repo import get_blood_banks, get_components, get_hospitals
from backend.schemas import BloodRequestCreate
from backend.services.allocation_service import (
    confirm_fefo_allocation,
    preview_fefo_allocation,
    reverse_allocation,
)
from backend.services.request_service import (
    approve_request,
    cancel_request,
    create_blood_request,
    list_allocations_for_request_df,
    list_requests_df,
    mark_request_issued,
    reject_request,
)


def render_requests_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header(
        "Requests",
        "Blood Requests & FEFO Allocation",
        "Process hospital blood requests, preview First Expiry, First Out (FEFO) allocations, reverse reservations, and confirm authorized handovers.",
    )

    all_reqs = list_requests_df(session, blood_bank_id=blood_bank_id)
    open_set = {"Submitted", "Under Review", "Approved", "Partially Allocated", "Fully Allocated"}
    open_cnt = int(all_reqs[all_reqs["status"].isin(open_set)].shape[0]) if not all_reqs.empty else 0
    urgent_open = (
        int(all_reqs[all_reqs["status"].isin(open_set) & all_reqs["urgency"].isin(["Urgent", "Emergency"])].shape[0])
        if not all_reqs.empty
        else 0
    )
    unful_qty = (
        int(all_reqs[all_reqs["status"].isin({"Submitted", "Under Review", "Approved", "Partially Allocated"})]["remaining_quantity"].sum())
        if not all_reqs.empty
        else 0
    )
    issued_cnt = int((all_reqs["status"] == "Issued").sum()) if not all_reqs.empty else 0
    total_req_u = int(all_reqs[~all_reqs["status"].isin(["Cancelled", "Rejected"])]["required_quantity"].sum()) if not all_reqs.empty else 0
    total_ful_u = int(all_reqs[~all_reqs["status"].isin(["Cancelled", "Rejected"])]["allocated_quantity"].sum()) if not all_reqs.empty else 0
    ful_rate = f"{(total_ful_u / max(1, total_req_u) * 100):.1f}%"

    render_kpi_strip(
        [
            {"label": "Open Requests", "value": f"{open_cnt:,}", "meta": "Active workflow queue", "tone": "accent"},
            {"label": "Open Urgent / Emergency", "value": f"{urgent_open:,}", "meta": "Administrative priority labels", "tone": "critical" if urgent_open else ""},
            {"label": "Open Remaining Units", "value": f"{unful_qty:,}", "meta": "Units awaiting FEFO allocation", "tone": "warning" if unful_qty else ""},
            {"label": "Issued Requests", "value": f"{issued_cnt:,}", "meta": "Handed over to hospitals", "tone": ""},
            {"label": "Overall Fulfilment Rate", "value": ful_rate, "meta": f"{total_ful_u:,} / {total_req_u:,} units", "tone": "accent"},
        ]
    )

    tab_queue, tab_allocate, tab_new = st.tabs(
        ["Request Queue", "Manage & FEFO Allocate", "Create Hospital Request"]
    )

    comps = [c.component_name for c in get_components(session)]
    hospitals = get_hospitals(session)
    hosp_names = [h.hospital_name for h in hospitals]

    with tab_queue:
        f1, f2 = st.columns([2, 3])
        with f1:
            search_ref = st.text_input("Search Request ID", placeholder="e.g. REQ-01180", key="req_search")
        with f2:
            sel_bg, sel_comp = render_blood_group_component_filters(comps, "req")

        f3, f4, f5 = st.columns(3)
        with f3:
            sel_status = st.multiselect(
                "Request Status",
                options=REQUEST_STATUSES,
                default=["Submitted", "Under Review", "Approved", "Partially Allocated", "Fully Allocated"],
                key="req_status_f",
            )
        with f4:
            sel_urg = st.multiselect("Urgency Category", options=REQUEST_URGENCIES, default=[], key="req_urg_f", placeholder="All urgencies")
        with f5:
            sel_hosp = st.selectbox("Hospital", options=["All"] + hosp_names, key="req_hosp_f")

        filtered = list_requests_df(
            session,
            blood_bank_id=blood_bank_id,
            blood_groups=sel_bg or None,
            components=sel_comp or None,
            statuses=sel_status or None,
            urgencies=sel_urg or None,
            hospital_name=sel_hosp,
            search_ref=search_ref,
        )
        st.caption(f"Showing {len(filtered):,} request(s). Urgency tags are administrative request labels only.")
        render_clean_table(filtered, hide_columns=["id", "notes"], height=400)

    with tab_allocate:
        actionable = all_reqs[all_reqs["status"].isin(["Submitted", "Under Review", "Approved", "Partially Allocated", "Fully Allocated"])] if not all_reqs.empty else pd.DataFrame()
        if actionable.empty:
            render_empty_state("No open requests available to review or allocate.")
        else:
            req_map = {
                f"{r['request_reference']} | {r['hospital']} | {r['blood_group']} {r['component']} | "
                f"{r['allocated_quantity']}/{r['required_quantity']} ({r['status']} — {r['urgency']})": int(r["id"])
                for _, r in actionable.head(60).iterrows()
            }
            selected_lbl = st.selectbox("Select Active Request", options=list(req_map.keys()), key="manage_req_sel")
            req_id = req_map[selected_lbl]
            req_row = actionable[actionable["id"] == req_id].iloc[0]

            render_html(
                f"""
                <div class="sv-panel">
                    <div style="font-weight:600; font-size:14.5px; color:#0F172A;">
                        <span class="sv-bg-pill">{req_row['blood_group']}</span>
                        {req_row['request_reference']} — {req_row['hospital']}
                    </div>
                    <div style="font-size:12.5px; color:#475569; margin-top:6px;">
                        Component: <strong>{req_row['component']}</strong> &nbsp;|&nbsp;
                        Requested: <strong>{req_row['required_quantity']}</strong> &nbsp;|&nbsp;
                        Allocated: <strong>{req_row['allocated_quantity']}</strong> &nbsp;|&nbsp;
                        Remaining: <strong>{req_row['remaining_quantity']}</strong> &nbsp;|&nbsp;
                        Urgency: <strong>{req_row['urgency']}</strong> &nbsp;|&nbsp;
                        Status: <strong>{req_row['status']}</strong>
                    </div>
                </div>
                """
            )

            act_col, fefo_col = st.columns([1.2, 2.0])

            with act_col:
                render_section_title("Workflow Actions")
                if req_row["status"] in ("Submitted", "Under Review"):
                    if st.button("Approve Request", type="primary", width="stretch", key="btn_approve_req"):
                        try:
                            approve_request(session, req_id, actor=actor, note="Approved for FEFO allocation")
                            session.commit()
                            st.success(f"Request {req_row['request_reference']} approved.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

                if req_row["status"] in ("Partially Allocated", "Fully Allocated"):
                    handover_note = st.text_input("Handover / Dispatch Note", value="Verified cold-chain handover", key="handover_note_in")
                    if st.button("Confirm Authorized Handover (Mark Issued)", type="primary", width="stretch", key="btn_issue_req"):
                        try:
                            mark_request_issued(session, req_id, actor=actor, handover_note=handover_note)
                            session.commit()
                            st.success(f"Reserved units for {req_row['request_reference']} marked Issued.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

                with st.expander("Reject or Cancel Request"):
                    reason_in = st.text_input("Mandatory Reason", key="req_cancel_reason", placeholder="Specify operational reason")
                    c_rej, c_can = st.columns(2)
                    with c_rej:
                        if req_row["status"] in ("Submitted", "Under Review", "Approved") and req_row["allocated_quantity"] == 0:
                            if st.button("Reject", width="stretch", key="btn_reject_req"):
                                try:
                                    reject_request(session, req_id, reason_in, actor=actor)
                                    session.commit()
                                    st.success("Request rejected.")
                                    st.rerun()
                                except Exception as exc:
                                    session.rollback()
                                    render_validation_error(exc)
                    with c_can:
                        if st.button("Cancel & Release Stock", width="stretch", key="btn_cancel_req"):
                            try:
                                cancel_request(session, req_id, reason_in or "Cancelled by administrator", actor=actor)
                                session.commit()
                                st.success("Request cancelled and any reserved units restored.")
                                st.rerun()
                            except Exception as exc:
                                session.rollback()
                                render_validation_error(exc)

            with fefo_col:
                render_section_title("FEFO Allocation Preview & Confirmation")
                if req_row["status"] in ("Approved", "Partially Allocated") and req_row["remaining_quantity"] > 0:
                    qty_to_alloc = st.number_input(
                        "Units to Allocate",
                        min_value=1,
                        max_value=int(req_row["remaining_quantity"]),
                        value=int(req_row["remaining_quantity"]),
                        key="fefo_qty_input",
                    )
                    try:
                        preview = preview_fefo_allocation(session, req_id, quantity=int(qty_to_alloc))
                        st.warning(preview.advisory_message)
                        if not preview.proposed_units:
                            render_empty_state(
                                f"No eligible released {req_row['blood_group']} {req_row['component']} units are currently available in this blood bank."
                            )
                        else:
                            prop_df = pd.DataFrame(preview.proposed_units)
                            st.caption(
                                f"Proposed FEFO order (earliest expiry first): {len(prop_df)} unit(s) matched"
                                + (f" — {preview.unfulfilled_quantity} unit(s) shortfall." if preview.unfulfilled_quantity > 0 else ".")
                            )
                            render_clean_table(prop_df, hide_columns=["unit_id"], height=210)
                            ack = st.checkbox(
                                "I acknowledge this is an administrative allocation and that clinical compatibility must be verified by authorized personnel.",
                                value=False,
                                key="fefo_human_ack",
                            )
                            if st.button("Confirm FEFO Allocation", type="primary", disabled=not ack, key="btn_confirm_fefo"):
                                try:
                                    res = confirm_fefo_allocation(
                                        session,
                                        request_id=req_id,
                                        actor=actor,
                                        quantity=int(qty_to_alloc),
                                        human_approval_confirmed=ack,
                                    )
                                    session.commit()
                                    st.success(
                                        f"Allocated {res['allocated_count']} unit(s) ({', '.join(res['allocated_units'])}). "
                                        f"Request status: {res['request_status']}."
                                    )
                                    st.rerun()
                                except Exception as exc:
                                    session.rollback()
                                    render_validation_error(exc)
                    except Exception as exc:
                        render_validation_error(exc)
                else:
                    st.info("Approve the request first (or confirm handover if already fully allocated).")

            render_section_title("Allocation History for Selected Request")
            alloc_df = list_allocations_for_request_df(session, req_id)
            render_clean_table(alloc_df, hide_columns=["unit_id"], height=210)

            if not alloc_df.empty:
                rev_candidates = alloc_df[alloc_df["allocation_status"] == "Reserved"]
                if not rev_candidates.empty:
                    with st.expander("Reverse an Active Reservation"):
                        rev_opts = {
                            f"Alloc #{r['allocation_id']} — {r['unit_reference']} (Exp {r['expiry_date']})": int(r["allocation_id"])
                            for _, r in rev_candidates.iterrows()
                        }
                        sel_rev = st.selectbox("Select Reserved Allocation", options=list(rev_opts.keys()), key="rev_alloc_sel")
                        rev_reason = st.text_input("Reversal Reason", value="Hospital order quantity adjusted", key="rev_alloc_reason")
                        if st.button("Reverse Reservation", key="btn_reverse_alloc"):
                            try:
                                reverse_allocation(session, rev_opts[sel_rev], rev_reason, actor=actor)
                                session.commit()
                                st.success("Reservation reversed and unit returned to inventory.")
                                st.rerun()
                            except Exception as exc:
                                session.rollback()
                                render_validation_error(exc)

    with tab_new:
        render_section_title("Submit New Hospital Blood Request")
        banks = get_blood_banks(session)
        bank_map = {b.bank_name: b.id for b in banks}
        hosp_map = {h.hospital_name: h.id for h in hospitals}
        enabled_comps = [c.component_name for c in get_components(session, only_enabled=True)]

        with st.form("create_request_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                r_ref = st.text_input("Request ID *", placeholder="REQ-90001")
                h_name = st.selectbox("Requesting Hospital *", options=list(hosp_map.keys()))
                b_name = st.selectbox("Fulfilling Blood Bank *", options=list(bank_map.keys()))
            with c2:
                bg_val = st.selectbox("Blood Group *", options=BLOOD_GROUP_NAMES)
                comp_val = st.selectbox("Blood Component *", options=enabled_comps)
                qty_val = st.number_input("Required Units *", min_value=1, max_value=100, value=2)
            with c3:
                urg_val = st.selectbox("Administrative Urgency *", options=REQUEST_URGENCIES)
                req_dt = st.date_input("Request Date *", value=date.today())
                need_dt = st.date_input("Required By Date *", value=date.today() + timedelta(days=1))
            notes_val = st.text_area("Operational Notes", height=65)

            if st.form_submit_button("Submit Blood Request", type="primary"):
                try:
                    payload = BloodRequestCreate(
                        request_reference=r_ref,
                        blood_bank_id=bank_map[b_name],
                        hospital_id=hosp_map[h_name],
                        blood_group=bg_val,
                        component_name=comp_val,
                        required_quantity=int(qty_val),
                        urgency=urg_val,
                        request_date=req_dt,
                        required_date=need_dt,
                        notes=notes_val,
                    )
                    created = create_blood_request(session, payload, actor=actor)
                    session.commit()
                    st.success(f"Blood request {created.request_reference} submitted.")
                    st.rerun()
                except Exception as exc:
                    session.rollback()
                    render_validation_error(exc)
