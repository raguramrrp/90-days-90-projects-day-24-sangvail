"""Patient & Requester Portal — Live Blood Availability, Requests, Surgery Holds, Transport & Receipts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from app.components.forms import render_validation_error
from app.components.navigation import render_html, render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from app.config import BLOOD_GROUP_NAMES, REQUEST_URGENCIES
from app.pages.network_dispatch import _chart_regional_hub_map
from backend.repositories.master_repo import get_blood_banks, get_components, get_hospitals
from backend.schemas import BloodRequestCreate
from backend.services.inventory_service import get_stock_by_group_and_component
from backend.services.network_dispatch_service import (
    PAYMENT_METHODS,
    SURGERY_PROCEDURES,
    TRANSPORT_MODES,
    arrange_transport_dispatch,
    cancel_surgical_booking,
    create_surgical_booking,
    estimate_service_charges,
    find_nearest_storage_hubs,
    generate_payment_receipt_pdf,
    list_dispatches_df,
    list_payments_df,
    list_surgical_bookings_df,
    record_service_payment,
)
from backend.services.request_service import cancel_request, create_blood_request, list_requests_df


def render_patient_portal_page(session: Session, user: dict, active_tab: str) -> None:
    """Render role-scoped Patient / User Portal views."""
    username = user["username"]
    banks = get_blood_banks(session)
    hospitals = get_hospitals(session)
    comps = get_components(session, only_enabled=True)
    comp_names = [c.component_name for c in comps]
    hosp_map = {h.hospital_name: h for h in hospitals}
    bank_map = {b.bank_name: b for b in banks}

    my_reqs_df = list_requests_df(session, created_by=username)
    all_bookings_df = list_surgical_bookings_df(session)
    my_req_refs = set(my_reqs_df["request_reference"].tolist()) if not my_reqs_df.empty else set()
    my_bookings_df = (
        all_bookings_df[all_bookings_df["request_reference"].isin(my_req_refs)]
        if not all_bookings_df.empty and my_req_refs
        else pd.DataFrame()
    )
    all_disp_df = list_dispatches_df(session)
    my_disp_df = (
        all_disp_df[all_disp_df["request_reference"].isin(my_req_refs)]
        if not all_disp_df.empty and my_req_refs
        else pd.DataFrame()
    )
    all_pay_df = list_payments_df(session)
    my_pay_df = (
        all_pay_df[all_pay_df["request_reference"].isin(my_req_refs)]
        if not all_pay_df.empty and my_req_refs
        else pd.DataFrame()
    )

    # -----------------------------------------------------------------------
    # VIEW 1: Live Blood Availability & Nearest Storage Hubs
    # -----------------------------------------------------------------------
    if active_tab == "Availability":
        render_page_header("Availability", "Live Blood Availability")

        stock_df = get_stock_by_group_and_component(session)
        group_avail = {bg: 0 for bg in BLOOD_GROUP_NAMES}
        if not stock_df.empty:
            agg_bg = stock_df.groupby("blood_group", as_index=False)["available"].sum()
            for _, row in agg_bg.iterrows():
                if row["blood_group"] in group_avail:
                    group_avail[row["blood_group"]] = int(row["available"])

        bg_tiles = []
        for bg in BLOOD_GROUP_NAMES:
            avail_n = group_avail[bg]
            dot_cls = "crit" if avail_n <= 3 else ("warn" if avail_n <= 10 else "safe")
            bg_tiles.append(
                f'<div class="sv-bg-tile">'
                f'<div class="sv-bg-tile-top">'
                f'<span class="sv-bg-pill" style="margin-right:0;">{bg}</span>'
                f'<span class="sv-bg-status-dot {dot_cls}"></span>'
                f'</div>'
                f'<div class="sv-bg-count">{avail_n:,}<span>units</span></div>'
                f'</div>'
            )
        render_html(f'<div class="sv-bg-grid">{"".join(bg_tiles)}</div>')

        render_section_title("Find Nearest Storage Hub with Live Stock")
        f1, f2, f3, f4 = st.columns([2.2, 1.1, 1.8, 1.0])
        with f1:
            sel_hosp = st.selectbox("Your Hospital / Treatment Center", options=list(hosp_map.keys()), key="pt_hosp_sel")
            h_obj = hosp_map[sel_hosp]
        with f2:
            sel_bg = st.selectbox("Blood Group Needed", options=BLOOD_GROUP_NAMES, index=6, key="pt_bg_sel")
        with f3:
            sel_comp = st.selectbox("Component Needed", options=comp_names, index=0, key="pt_comp_sel")
        with f4:
            qty_need = st.number_input("Units", min_value=1, max_value=20, value=2, key="pt_qty_sel")

        hubs_df = find_nearest_storage_hubs(
            session,
            blood_group=sel_bg,
            component_name=sel_comp,
            quantity_needed=int(qty_need),
            hospital_id=h_obj.id,
        )

        col_m, col_h = st.columns([1.45, 1.35], gap="large")
        with col_m:
            st.plotly_chart(
                _chart_regional_hub_map(hubs_df, h_obj.hospital_name, h_obj.latitude, h_obj.longitude),
                width="stretch",
            )
        with col_h:
            for _, row in hubs_df.iterrows():
                badge_cls = "normal" if row["can_fulfill_full"] else ("warning" if row["available_units"] > 0 else "critical")
                render_html(
                    f"""
                    <div class="sv-alert-row {badge_cls}">
                        <div class="sv-alert-title">
                            <span class="sv-badge {badge_cls}">{row['availability_status']}</span>
                            <span class="sv-bg-pill">{sel_bg}</span>
                            {row['hub_name']} &nbsp;·&nbsp; <strong>{int(row['available_units'])} units</strong>
                        </div>
                        <div class="sv-alert-detail">
                            {row['distance_km']:.1f} km away (~{int(row['est_transit_min'])} min cold-chain transit) &nbsp;|&nbsp; {row['address']} &nbsp;|&nbsp; {row['contact']}
                        </div>
                    </div>
                    """
                )

        render_section_title("Component-Wise Available Stock Across All Hubs")
        if not stock_df.empty:
            clean_av = stock_df[["blood_group", "component", "available"]].sort_values(["blood_group", "component"])
            render_clean_table(clean_av, height=310)

    # -----------------------------------------------------------------------
    # VIEW 2: Submit Blood Request Form
    # -----------------------------------------------------------------------
    elif active_tab == "New Request":
        render_page_header("New Request", "Submit Blood Request")

        c_form, c_guide = st.columns([1.5, 1.1], gap="large")
        with c_form:
            with st.form("patient_new_request_form", clear_on_submit=True):
                r1, r2 = st.columns(2)
                with r1:
                    h_name = st.selectbox("Hospital *", options=list(hosp_map.keys()))
                    bg_val = st.selectbox("Blood Group *", options=BLOOD_GROUP_NAMES, index=6)
                    qty_val = st.number_input("Required Units *", min_value=1, max_value=20, value=2)
                with r2:
                    b_name = st.selectbox("Preferred Storage Hub *", options=list(bank_map.keys()))
                    comp_val = st.selectbox("Blood Component *", options=comp_names, index=0)
                    urg_val = st.selectbox("Urgency *", options=REQUEST_URGENCIES, index=1)

                d1, d2 = st.columns(2)
                with d1:
                    need_dt = st.date_input("Required By Date *", value=date.today(), min_value=date.today())
                with d2:
                    ward_ref = st.text_input("Hospital Case / Ward Reference", placeholder="e.g. Ward 4B / Bed 12")
                notes_val = st.text_area("Additional Notes for Blood Bank Coordinator", height=80)

                if st.form_submit_button("Submit Blood Request", type="primary", width="stretch"):
                    try:
                        ts_code = datetime.now(timezone.utc).strftime("%H%M%S%f")[:10]
                        req_ref = f"REQ-USR-{ts_code}"
                        full_notes = f"Case/Ward: {ward_ref}. {notes_val}".strip(" .") if ward_ref else notes_val
                        created = create_blood_request(
                            session,
                            BloodRequestCreate(
                                request_reference=req_ref,
                                blood_bank_id=bank_map[b_name].id,
                                hospital_id=hosp_map[h_name].id,
                                blood_group=bg_val,
                                component_name=comp_val,
                                required_quantity=int(qty_val),
                                urgency=urg_val,
                                request_date=date.today(),
                                required_date=need_dt,
                                notes=full_notes,
                            ),
                            actor=username,
                        )
                        session.commit()
                        st.success(
                            f"Request {created.request_reference} submitted to {b_name}. "
                            "Track approval and allocation progress under My Requests."
                        )
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

        with c_guide:
            render_html(
                """
                <div class="sv-panel">
                    <div style="font-weight:600; font-size:14.5px; color:#0F172A; margin-bottom:10px;">How Blood Requests Are Processed</div>
                    <div style="font-size:13px; color:#475569; line-height:1.6;">
                        <strong>1. Submission:</strong> Your request enters the selected blood bank's live review queue immediately.<br/><br/>
                        <strong>2. FEFO Allocation:</strong> Blood bank staff verify eligibility and reserve units using First Expiry, First Out rules.<br/><br/>
                        <strong>3. Cold-Chain Dispatch:</strong> Once reserved, you can schedule validated cold-chain transport and settle processing fees from <em>My Requests</em>.
                    </div>
                </div>
                """
            )

    # -----------------------------------------------------------------------
    # VIEW 3: Surgery Pre-Reservation
    # -----------------------------------------------------------------------
    elif active_tab == "Surgery Booking":
        render_page_header("Surgery Booking", "Pre-Reserve Blood for Surgery")

        c_bk, c_my = st.columns([1.2, 1.8], gap="large")
        with c_bk:
            render_section_title("Book Surgical Blood Hold")
            with st.form("patient_surgery_form"):
                s_hosp = st.selectbox("Hospital *", options=list(hosp_map.keys()))
                s_hub = st.selectbox("Storage Hub *", options=list(bank_map.keys()))
                s_proc = st.selectbox("Procedure Category *", options=SURGERY_PROCEDURES)
                sc1, sc2 = st.columns(2)
                with sc1:
                    s_bg = st.selectbox("Blood Group *", options=BLOOD_GROUP_NAMES, index=6)
                with sc2:
                    s_qty = st.number_input("Units to Hold *", min_value=1, max_value=10, value=2)
                s_comp = st.selectbox("Component *", options=comp_names, index=0)
                sd1, sd2 = st.columns(2)
                with sd1:
                    s_date = st.date_input("Surgery Date *", value=date.today() + timedelta(days=2), min_value=date.today())
                with sd2:
                    s_hold = st.date_input("Hold Until Date *", value=date.today() + timedelta(days=3), min_value=date.today())
                s_note = st.text_input("OT / Physician Reference", placeholder="e.g. OT-2 Morning Schedule")
                if st.form_submit_button("Reserve Units for Surgery", type="primary", width="stretch"):
                    try:
                        res = create_surgical_booking(
                            session,
                            hospital_id=hosp_map[s_hosp].id,
                            blood_bank_id=bank_map[s_hub].id,
                            blood_group=s_bg,
                            component_name=s_comp,
                            quantity=int(s_qty),
                            procedure_category=s_proc,
                            surgery_date=s_date,
                            hold_until_date=s_hold,
                            human_approval_confirmed=True,
                            notes=s_note,
                            actor=username,
                        )
                        session.commit()
                        st.success(
                            f"Surgical booking {res['booking_reference']} confirmed for {res['surgery_date']}. "
                            f"Reserved units: {', '.join(res['reserved_units'])}."
                        )
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

        with c_my:
            render_section_title("My Surgical Blood Holds")
            render_clean_table(my_bookings_df, hide_columns=["id", "notes"], height=310)
            active_my_bk = my_bookings_df[my_bookings_df["status"] == "Reserved"] if not my_bookings_df.empty else pd.DataFrame()
            if not active_my_bk.empty:
                bk_opts = {
                    f"{r['booking_reference']} | {r['blood_group']} {r['component']} x{r['quantity']} ({r['surgery_date']})": int(r["id"])
                    for _, r in active_my_bk.iterrows()
                }
                sel_bk = st.selectbox("Cancel / Release Surgical Hold", options=list(bk_opts.keys()), key="pt_cancel_bk_sel")
                if st.button("Release Hold", key="pt_cancel_bk_btn"):
                    try:
                        cancel_surgical_booking(session, bk_opts[sel_bk], "Cancelled by requester", actor=username)
                        session.commit()
                        st.success("Surgical hold released.")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

    # -----------------------------------------------------------------------
    # VIEW 4: My Requests & Cold-Chain Transport Tracking
    # -----------------------------------------------------------------------
    elif active_tab == "My Requests":
        render_page_header("My Requests", "My Requests & Dispatch Tracking")

        total_r = len(my_reqs_df)
        open_r = int(my_reqs_df[my_reqs_df["status"].isin(["Submitted", "Under Review", "Approved", "Partially Allocated", "Fully Allocated"])].shape[0]) if not my_reqs_df.empty else 0
        alloc_u = int(my_reqs_df["allocated_quantity"].sum()) if not my_reqs_df.empty else 0
        disp_n = len(my_disp_df)

        render_kpi_strip(
            [
                {"label": "Total Submitted Requests", "value": str(total_r), "meta": f"Account: {username}", "tone": "accent"},
                {"label": "Active Requests", "value": str(open_r), "meta": "Pending / allocated", "tone": "warning" if open_r else ""},
                {"label": "Reserved / Issued Units", "value": str(alloc_u), "meta": "Units assigned to you", "tone": "accent"},
                {"label": "Transport Dispatches", "value": str(disp_n), "meta": "Cold-chain deliveries", "tone": ""},
            ]
        )

        render_section_title("My Blood Requests")
        render_clean_table(my_reqs_df, hide_columns=["id", "notes"], height=280)

        c_can, c_trn = st.columns(2, gap="large")
        with c_can:
            render_section_title("Cancel an Open Request")
            cancellable = my_reqs_df[my_reqs_df["status"].isin(["Submitted", "Under Review", "Approved", "Partially Allocated", "Fully Allocated"])] if not my_reqs_df.empty else pd.DataFrame()
            if cancellable.empty:
                render_empty_state("No open requests available to cancel.")
            else:
                c_opts = {f"{r['request_reference']} ({r['blood_group']} {r['component']} · {r['status']})": int(r["id"]) for _, r in cancellable.iterrows()}
                sel_c = st.selectbox("Select Request", options=list(c_opts.keys()), key="pt_can_req_sel")
                c_reason = st.text_input("Cancellation Reason", value="No longer required", key="pt_can_req_reason")
                if st.button("Cancel Request", width="stretch", key="pt_can_req_btn"):
                    try:
                        cancel_request(session, c_opts[sel_c], c_reason, actor=username)
                        session.commit()
                        st.success("Request cancelled.")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

        with c_trn:
            render_section_title("Arrange Cold-Chain Transport")
            alloc_reqs = my_reqs_df[my_reqs_df["status"].isin(["Partially Allocated", "Fully Allocated", "Issued"])] if not my_reqs_df.empty else pd.DataFrame()
            if alloc_reqs.empty:
                render_empty_state("Transport can be arranged once your request or surgery hold has allocated units.")
            else:
                t_opts = {f"{r['request_reference']} ({r['blood_group']} {r['component']} · {r['allocated_quantity']}u)": int(r["id"]) for _, r in alloc_reqs.iterrows()}
                with st.form("pt_transport_form"):
                    sel_t = st.selectbox("Allocated Request *", options=list(t_opts.keys()))
                    t_mode = st.selectbox("Transport Mode *", options=list(TRANSPORT_MODES.keys()))
                    t_box = st.text_input("Insulated Container Preference", value="THERMO-BOX-STD")
                    if st.form_submit_button("Request Cold-Chain Pickup", type="primary", width="stretch"):
                        try:
                            disp = arrange_transport_dispatch(
                                session,
                                request_id=t_opts[sel_t],
                                transport_mode=t_mode,
                                vehicle_reference="ASSIGNED-ON-DISPATCH",
                                courier_name="Assigned Logistics Team",
                                container_id=t_box,
                                notes=f"Requested via Patient Portal by {username}",
                                actor=username,
                            )
                            session.commit()
                            st.success(f"Transport {disp.dispatch_reference} scheduled (ETA ~{disp.eta_minutes} min).")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

        render_section_title("My Cold-Chain Dispatch Status")
        render_clean_table(my_disp_df, hide_columns=["id"], height=230)

    # -----------------------------------------------------------------------
    # VIEW 5: Processing Fees & Receipts
    # -----------------------------------------------------------------------
    elif active_tab == "Payments":
        render_page_header("Payments", "Processing Fees & Online Settlement")

        c_pay, c_rec = st.columns([1.15, 1.85], gap="large")
        with c_pay:
            render_section_title("Settle Processing & Logistics Fee")
            eligible_bill = my_reqs_df[~my_reqs_df["status"].isin(["Cancelled", "Rejected"])] if not my_reqs_df.empty else pd.DataFrame()
            if eligible_bill.empty:
                render_empty_state("Submit a blood request or surgery booking first to view itemized processing fees.")
            else:
                b_opts = {f"{r['request_reference']} | {r['blood_group']} {r['component']}": int(r["id"]) for _, r in eligible_bill.iterrows()}
                sel_b = st.selectbox("Select Your Request", options=list(b_opts.keys()), key="pt_pay_sel")
                req_id = b_opts[sel_b]
                req_code = sel_b.split(" | ")[0]
                disp_id = None
                if not my_disp_df.empty:
                    md = my_disp_df[my_disp_df["request_reference"] == req_code]
                    if not md.empty:
                        disp_id = int(md.iloc[0]["id"])

                est = estimate_service_charges(session, request_id=req_id, dispatch_id=disp_id)
                proc_part = round(est["component_service_fee"] * 0.75, 2)
                scr_part = round(est["component_service_fee"] - proc_part, 2)
                inv_date_str = date.today().strftime("%d-%b-%Y")
                render_html(
                    f"""
                    <div class="sv-panel" style="padding:0; overflow:hidden;">
                        <div style="background:#0F3D3E; color:#FFFFFF; padding:12px 16px; display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <div style="font-weight:700; font-size:13.5px; letter-spacing:0.06em;">SANGVAIL BLOOD SERVICES</div>
                                <div style="font-size:11px; color:#99F6E4;">License: BB-REG-2026-0412 &nbsp;·&nbsp; SAC 999311</div>
                            </div>
                            <div style="text-align:right; font-size:11px; color:#CCFBF1;">
                                <strong>SERVICE BILL</strong><br/>{inv_date_str}
                            </div>
                        </div>
                        <div style="padding:14px 16px;">
                            <div style="display:flex; justify-content:space-between; font-size:12px; color:#475569; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid #E2E8F0;">
                                <div>
                                    <span style="color:#94A3B8; font-size:10.5px; text-transform:uppercase; font-weight:600;">Billed To</span><br/>
                                    <strong style="color:#0F172A;">{est['hospital_name']}</strong><br/>
                                    <span>Patient Ref: Arjun K. · Case #IPD-2026-4812</span>
                                </div>
                                <div style="text-align:right;">
                                    <span style="color:#94A3B8; font-size:10.5px; text-transform:uppercase; font-weight:600;">Order Ref</span><br/>
                                    <strong style="color:#0F172A;">{est['request_reference']}</strong><br/>
                                    <span>{est['component_name']} (×{est['billable_units']})</span>
                                </div>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:12.5px; color:#334155; margin-bottom:5px;">
                                <span>1. Component Processing &amp; Cold Storage (×{est['billable_units']})</span>
                                <strong style="color:#0F172A;">INR {proc_part:,.2f}</strong>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:12.5px; color:#334155; margin-bottom:5px;">
                                <span>2. TTI Screening &amp; Bag Consumables Recovery</span>
                                <strong style="color:#0F172A;">INR {scr_part:,.2f}</strong>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:12.5px; color:#334155; margin-bottom:5px;">
                                <span>3. Cold-Chain Logistics ({est['transport_description']})</span>
                                <strong style="color:#0F172A;">INR {est['transport_fee']:,.2f}</strong>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:12px; color:#64748B; margin-bottom:9px;">
                                <span>Healthcare GST (0% Exempt — SAC 999311)</span>
                                <span>INR 0.00</span>
                            </div>
                            <div style="border-top:1.5px solid #0F766E; padding-top:9px; display:flex; justify-content:space-between; font-size:15px; font-weight:700; color:#0F766E;">
                                <span>Net Payable Total</span>
                                <span>INR {est['total_amount']:,.2f}</span>
                            </div>
                        </div>
                    </div>
                    """
                )
                with st.form("pt_payment_form"):
                    pm = st.selectbox("Payment Method *", options=PAYMENT_METHODS)
                    pnote = st.text_input("Reference Note", placeholder="Optional billing note")
                    if st.form_submit_button("Pay Online Now", type="primary", width="stretch"):
                        try:
                            pay = record_service_payment(
                                session,
                                request_id=req_id,
                                payment_method=pm,
                                dispatch_id=disp_id,
                                notes=pnote,
                                actor=username,
                            )
                            session.commit()
                            st.success(f"Payment {pay.payment_reference} completed (Ref: {pay.transaction_ref}).")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

        with c_rec:
            render_section_title("My Payment History & PDF Receipts")
            render_clean_table(my_pay_df, hide_columns=["id"], height=300)
            if not my_pay_df.empty:
                rc_opts = {f"{r['payment_reference']} — INR {r['total_amount']:,.2f}": int(r["id"]) for _, r in my_pay_df.iterrows()}
                rc1, rc2 = st.columns([2.0, 1.2], vertical_alignment="bottom")
                with rc1:
                    sel_rc = st.selectbox("Select Receipt", options=list(rc_opts.keys()), key="pt_rc_sel")
                with rc2:
                    pdf_bytes = generate_payment_receipt_pdf(session, rc_opts[sel_rc])
                    st.download_button(
                        "Download PDF Receipt",
                        data=pdf_bytes,
                        file_name=f"{sel_rc.split(' — ')[0]}_invoice.pdf",
                        mime="application/pdf",
                        type="primary",
                        width="stretch",
                    )
