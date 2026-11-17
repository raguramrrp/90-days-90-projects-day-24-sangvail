"""Network & Dispatch — Nearest Storage Hubs, Surgery Pre-Reservation, Cold-Chain Transport & Billing."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy.orm import Session

from app.components.forms import render_validation_error
from app.components.navigation import render_html, render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from app.config import BLOOD_GROUP_NAMES, REQUEST_URGENCIES
from backend.repositories.master_repo import get_blood_banks, get_components, get_hospitals
from backend.services.network_dispatch_service import (
    DISPATCH_FLOW,
    PAYMENT_METHODS,
    SURGERY_PROCEDURES,
    TRANSPORT_MODES,
    advance_dispatch_status,
    arrange_transport_dispatch,
    cancel_surgical_booking,
    complete_surgical_booking,
    create_surgical_booking,
    estimate_service_charges,
    find_nearest_storage_hubs,
    generate_payment_receipt_pdf,
    list_dispatches_df,
    list_payments_df,
    list_surgical_bookings_df,
    record_service_payment,
    request_and_reserve_from_hub,
)
from backend.services.request_service import list_requests_df


def _chart_regional_hub_map(hubs_df: pd.DataFrame, hospital_name: str, hosp_lat: float, hosp_lon: float) -> go.Figure:
    """Offline-safe regional coordinate map showing hospital and nearest blood storage hubs."""
    fig = go.Figure()
    if not hubs_df.empty:
        # Draw transit lines from hospital to hubs
        for _, r in hubs_df.iterrows():
            line_col = "#0F766E" if r["can_fulfill_full"] else ("#D97706" if r["available_units"] > 0 else "#CBD5E1")
            fig.add_trace(
                go.Scatter(
                    x=[hosp_lon, r["longitude"]],
                    y=[hosp_lat, r["latitude"]],
                    mode="lines",
                    line=dict(color=line_col, width=1.6, dash="dot"),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
        colors = [
            "#0F766E" if row["can_fulfill_full"] else ("#D97706" if row["available_units"] > 0 else "#E11D48")
            for _, row in hubs_df.iterrows()
        ]
        sizes = [max(16, min(32, 14 + int(row["available_units"]) * 1.4)) for _, row in hubs_df.iterrows()]
        fig.add_trace(
            go.Scatter(
                x=hubs_df["longitude"],
                y=hubs_df["latitude"],
                mode="markers+text",
                name="Blood Storage Hubs",
                marker=dict(size=sizes, color=colors, line=dict(color="#FFFFFF", width=2)),
                text=[f"{r['hub_name'].replace('Sangvail ', '')} ({r['available_units']}u · {r['distance_km']} km)" for _, r in hubs_df.iterrows()],
                textposition="top center",
                textfont=dict(size=11, color="#0F172A", family="Inter"),
                hovertemplate="<b>%{customdata[0]}</b><br>Available: %{customdata[1]} units<br>Distance: %{customdata[2]} km (~%{customdata[3]} min)<extra></extra>",
                customdata=hubs_df[["hub_name", "available_units", "distance_km", "est_transit_min"]].values,
            )
        )

    fig.add_trace(
        go.Scatter(
            x=[hosp_lon],
            y=[hosp_lat],
            mode="markers+text",
            name="Requesting Hospital",
            marker=dict(size=18, color="#0284C7", symbol="diamond", line=dict(color="#FFFFFF", width=2)),
            text=[hospital_name],
            textposition="bottom center",
            textfont=dict(size=11.5, color="#0284C7", family="Plus Jakarta Sans, Inter"),
            hovertemplate=f"<b>{hospital_name}</b><br>Origin Point<extra></extra>",
        )
    )

    fig.update_layout(
        title=dict(text="Regional Blood Hub Proximity & Live Availability", font=dict(size=14.5, color="#0F172A", family="Plus Jakarta Sans, Inter"), x=0.01),
        height=350,
        margin=dict(l=16, r=16, t=44, b=28),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFC",
        xaxis=dict(title="Longitude", gridcolor="#E2E8F0", griddash="dot", tickfont=dict(size=10.5, color="#64748B")),
        yaxis=dict(title="Latitude", gridcolor="#E2E8F0", griddash="dot", tickfont=dict(size=10.5, color="#64748B")),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0, font=dict(size=11.5, color="#475569")),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#E2E8F0", font=dict(size=12, color="#0F172A")),
    )
    return fig


def render_network_dispatch_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header("Network", "Network, Surgery Booking & Dispatch")

    banks = get_blood_banks(session)
    hospitals = get_hospitals(session)
    comps = get_components(session, only_enabled=True)
    comp_names = [c.component_name for c in comps]

    bookings_df = list_surgical_bookings_df(session, blood_bank_id=blood_bank_id)
    dispatches_df = list_dispatches_df(session, blood_bank_id=blood_bank_id)
    payments_df = list_payments_df(session)

    active_bookings = int((bookings_df["status"] == "Reserved").sum()) if not bookings_df.empty else 0
    active_dispatches = (
        int(dispatches_df["status"].isin(["Scheduled", "Dispatched", "In Transit"]).sum())
        if not dispatches_df.empty
        else 0
    )
    total_settled = float(payments_df["total_amount"].sum()) if not payments_df.empty else 0.0

    render_kpi_strip(
        [
            {"label": "Regional Storage Hubs", "value": str(len(banks)), "meta": "Active cold-chain nodes", "tone": "accent"},
            {"label": "Active Surgery Holds", "value": str(active_bookings), "meta": "Pre-reserved surgical bookings", "tone": "warning" if active_bookings else ""},
            {"label": "Active Dispatches", "value": str(active_dispatches), "meta": "Scheduled / In Transit", "tone": "accent" if active_dispatches else ""},
            {"label": "Service Fees Settled", "value": f"INR {total_settled:,.0f}", "meta": f"{len(payments_df)} billing record(s)", "tone": ""},
        ]
    )

    tab_nearest, tab_surgery, tab_transport, tab_billing = st.tabs(
        [
            "Nearest Storage Hubs",
            "Surgery Pre-Reservation",
            "Cold-Chain Transport",
            "Service Fees & Settlement",
        ]
    )

    hosp_map = {h.hospital_name: h for h in hospitals}
    bank_map = {b.bank_name: b for b in banks}

    # -----------------------------------------------------------------------
    # TAB 1: Nearest Storage Units Live Stock & Rapid Request
    # -----------------------------------------------------------------------
    with tab_nearest:
        f1, f2, f3, f4 = st.columns([2.2, 1.1, 1.8, 1.0])
        with f1:
            sel_hosp_name = st.selectbox("Requesting Hospital", options=list(hosp_map.keys()), key="net_hosp_sel")
            hosp_obj = hosp_map[sel_hosp_name]
        with f2:
            sel_bg = st.selectbox("Blood Group", options=BLOOD_GROUP_NAMES, index=6, key="net_bg_sel")
        with f3:
            sel_comp = st.selectbox("Component", options=comp_names, index=0, key="net_comp_sel")
        with f4:
            qty_needed = st.number_input("Units Needed", min_value=1, max_value=30, value=2, key="net_qty_sel")

        hubs_df = find_nearest_storage_hubs(
            session,
            blood_group=sel_bg,
            component_name=sel_comp,
            quantity_needed=int(qty_needed),
            hospital_id=hosp_obj.id,
        )

        col_map, col_req = st.columns([1.65, 1.15], gap="large")
        with col_map:
            st.plotly_chart(
                _chart_regional_hub_map(hubs_df, hosp_obj.hospital_name, hosp_obj.latitude, hosp_obj.longitude),
                width="stretch",
            )
            render_section_title(f"Live Nearby Availability — {sel_bg} · {sel_comp}")
            for _, row in hubs_df.iterrows():
                badge_cls = "normal" if row["can_fulfill_full"] else ("warning" if row["available_units"] > 0 else "critical")
                exp_txt = str(row["earliest_expiry"]) if pd.notna(row["earliest_expiry"]) and row["earliest_expiry"] else "None"
                render_html(
                    f"""
                    <div class="sv-alert-row {badge_cls}">
                        <div class="sv-alert-title">
                            <span class="sv-badge {badge_cls}">{row['availability_status']}</span>
                            <span class="sv-bg-pill">{sel_bg}</span>
                            {row['hub_name']} &nbsp;·&nbsp; <strong>{int(row['available_units'])} units available</strong>
                        </div>
                        <div class="sv-alert-detail">
                            Distance: <strong>{row['distance_km']:.1f} km</strong> (~{int(row['est_transit_min'])} min cold-chain transit) &nbsp;|&nbsp;
                            Earliest Expiry: <strong>{exp_txt}</strong> &nbsp;|&nbsp; {row['address']}
                        </div>
                    </div>
                    """
                )

        with col_req:
            render_section_title("Request & Reserve from Nearest Hub")
            hub_opts = {
                f"{r['hub_name']} ({r['distance_km']:.1f} km · {int(r['available_units'])}u)": int(r["blood_bank_id"])
                for _, r in hubs_df.iterrows()
            }
            with st.form("nearest_hub_request_form"):
                chosen_hub_lbl = st.selectbox("Target Storage Hub *", options=list(hub_opts.keys()))
                urg_sel = st.selectbox("Urgency", options=REQUEST_URGENCIES, index=2)
                need_date = st.date_input("Required By Date", value=date.today())
                auto_res = st.checkbox("Approve & reserve FEFO units immediately", value=True)
                ack = st.checkbox("Confirm administrative label match (authorized clinical verification required prior to transfusion)", value=True)
                req_note = st.text_input("Dispatch / Ward Note", placeholder="e.g. Trauma Bay 2")
                if st.form_submit_button("Submit & Reserve from Hub", type="primary", width="stretch"):
                    try:
                        res = request_and_reserve_from_hub(
                            session,
                            hospital_id=hosp_obj.id,
                            blood_bank_id=hub_opts[chosen_hub_lbl],
                            blood_group=sel_bg,
                            component_name=sel_comp,
                            quantity=int(qty_needed),
                            urgency=urg_sel,
                            required_date=need_date,
                            auto_reserve=auto_res,
                            human_approval_confirmed=ack,
                            notes=req_note,
                            actor=actor,
                        )
                        session.commit()
                        if res["allocated_count"] > 0:
                            st.success(
                                f"Created {res['request_reference']} and reserved {res['allocated_count']} FEFO unit(s): "
                                f"{', '.join(res['allocated_units'])}."
                            )
                        else:
                            st.warning(f"Created {res['request_reference']} ({res['status']}), 0 eligible units currently at selected hub.")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

    # -----------------------------------------------------------------------
    # TAB 2: Surgery Pre-Reservation / Advance Booking
    # -----------------------------------------------------------------------
    with tab_surgery:
        c_form, c_list = st.columns([1.15, 1.85], gap="large")
        with c_form:
            render_section_title("Pre-Reserve Units for Scheduled Surgery")
            with st.form("surgical_booking_form"):
                s_hosp = st.selectbox("Hospital *", options=list(hosp_map.keys()), key="surg_hosp")
                s_hub = st.selectbox("Storage Hub *", options=list(bank_map.keys()), key="surg_hub")
                s_proc = st.selectbox("Surgical Procedure *", options=SURGERY_PROCEDURES, key="surg_proc")
                sc1, sc2 = st.columns(2)
                with sc1:
                    s_bg = st.selectbox("Blood Group *", options=BLOOD_GROUP_NAMES, index=6, key="surg_bg")
                with sc2:
                    s_qty = st.number_input("Units to Hold *", min_value=1, max_value=20, value=2, key="surg_qty")
                s_comp = st.selectbox("Component *", options=comp_names, index=0, key="surg_comp")
                sd1, sd2 = st.columns(2)
                with sd1:
                    s_date = st.date_input("Surgery Date *", value=date.today() + timedelta(days=2), min_value=date.today())
                with sd2:
                    s_hold = st.date_input("Hold Until Date *", value=date.today() + timedelta(days=3), min_value=date.today())
                s_notes = st.text_input("OT / Surgical Coordinator Note", placeholder="e.g. OT-3 Morning Slot")
                s_ack = st.checkbox("Confirm administrative hold (units validated not to expire before surgery date)", value=True)
                if st.form_submit_button("Confirm Surgical Pre-Reservation", type="primary", width="stretch"):
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
                            human_approval_confirmed=s_ack,
                            notes=s_notes,
                            actor=actor,
                        )
                        session.commit()
                        st.success(
                            f"Booking {res['booking_reference']} confirmed for {res['surgery_date']}. "
                            f"Reserved units: {', '.join(res['reserved_units'])}."
                        )
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

        with c_list:
            render_section_title("Scheduled Surgical Blood Holds")
            render_clean_table(bookings_df, hide_columns=["id", "notes"], height=330)

            active_bk = bookings_df[bookings_df["status"] == "Reserved"] if not bookings_df.empty else pd.DataFrame()
            if not active_bk.empty:
                render_section_title("Manage Active Surgical Hold")
                bk_opts = {
                    f"{r['booking_reference']} | {r['hospital']} | {r['blood_group']} {r['component']} x{r['quantity']} ({r['surgery_date']})": int(r["id"])
                    for _, r in active_bk.iterrows()
                }
                sel_bk = st.selectbox("Select Active Booking", options=list(bk_opts.keys()), key="manage_bk_sel")
                bk_note = st.text_input("Action Note", value="OT handover / schedule update", key="manage_bk_note")
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("Issue Units for Surgery", type="primary", width="stretch", key="btn_issue_surg"):
                        try:
                            complete_surgical_booking(session, bk_opts[sel_bk], bk_note, actor=actor)
                            session.commit()
                            st.success("Reserved surgical units issued.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)
                with b2:
                    if st.button("Release Hold & Return Stock", width="stretch", key="btn_cancel_surg"):
                        try:
                            cancel_surgical_booking(session, bk_opts[sel_bk], bk_note, actor=actor)
                            session.commit()
                            st.success("Surgical hold cancelled and units returned to available inventory.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

    # -----------------------------------------------------------------------
    # TAB 3: Cold-Chain Transport Arrangement & Tracking
    # -----------------------------------------------------------------------
    with tab_transport:
        reqs_df = list_requests_df(
            session,
            blood_bank_id=blood_bank_id,
            statuses=["Partially Allocated", "Fully Allocated", "Issued"],
        )
        c_arr, c_trk = st.columns([1.15, 1.85], gap="large")
        with c_arr:
            render_section_title("Arrange Cold-Chain Transport")
            if reqs_df.empty:
                render_empty_state("Allocate a hospital request or surgical booking before arranging transport.")
            else:
                req_opts = {
                    f"{r['request_reference']} | {r['hospital']} | {r['blood_group']} {r['component']} ({r['allocated_quantity']}u)": int(r["id"])
                    for _, r in reqs_df.head(40).iterrows()
                }
                with st.form("arrange_transport_form"):
                    sel_req_lbl = st.selectbox("Allocated Request *", options=list(req_opts.keys()))
                    t_mode = st.selectbox("Transport Mode *", options=list(TRANSPORT_MODES.keys()))
                    t_veh = st.text_input("Vehicle / Ambulance Plate *", value="CC-AMB-104")
                    t_cour = st.text_input("Assigned Courier / Paramedic *", value="Logistics Officer 01")
                    t_box = st.text_input("Validated Cool-Box / Container ID *", value="THERMO-BOX-07")
                    t_note = st.text_input("Cold-Chain Handling Note", placeholder="Seal number & logger check")
                    if st.form_submit_button("Schedule Cold-Chain Dispatch", type="primary", width="stretch"):
                        try:
                            disp = arrange_transport_dispatch(
                                session,
                                request_id=req_opts[sel_req_lbl],
                                transport_mode=t_mode,
                                vehicle_reference=t_veh,
                                courier_name=t_cour,
                                container_id=t_box,
                                notes=t_note,
                                actor=actor,
                            )
                            session.commit()
                            st.success(
                                f"Dispatch {disp.dispatch_reference} scheduled ({disp.distance_km:.1f} km, "
                                f"ETA ~{disp.eta_minutes} min, spec: {disp.required_temp_range})."
                            )
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

        with c_trk:
            render_section_title("Cold-Chain Dispatch Tracker")
            render_clean_table(dispatches_df, hide_columns=["id"], height=330)

            open_disp = dispatches_df[dispatches_df["status"] != "Delivered"] if not dispatches_df.empty else pd.DataFrame()
            if not open_disp.empty:
                render_section_title("Update Dispatch Custody Status")
                d_opts = {
                    f"{r['dispatch_reference']} ({r['request_reference']} · {r['status']})": int(r["id"])
                    for _, r in open_disp.iterrows()
                }
                uc1, uc2, uc3 = st.columns([2.0, 1.2, 1.0], vertical_alignment="bottom")
                with uc1:
                    sel_d_lbl = st.selectbox("Active Dispatch", options=list(d_opts.keys()), key="upd_disp_sel")
                with uc2:
                    next_st = st.selectbox("New Status", options=DISPATCH_FLOW[1:], key="upd_disp_st")
                with uc3:
                    if st.button("Update Status", type="primary", width="stretch", key="btn_upd_disp"):
                        try:
                            advance_dispatch_status(session, d_opts[sel_d_lbl], next_st, actor=actor)
                            session.commit()
                            st.success(f"Dispatch updated to '{next_st}'.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

    # -----------------------------------------------------------------------
    # TAB 4: Processing & Cold-Chain Service Fees + Online Payment (Simulated)
    # -----------------------------------------------------------------------
    with tab_billing:
        bill_reqs = list_requests_df(
            session,
            blood_bank_id=blood_bank_id,
            statuses=["Approved", "Partially Allocated", "Fully Allocated", "Issued"],
        )
        c_pay, c_led = st.columns([1.15, 1.85], gap="large")
        with c_pay:
            render_section_title("Processing & Logistics Settlement")
            st.caption("Charges cover component processing, screening, and cold-chain logistics cost recovery only.")
            if bill_reqs.empty:
                render_empty_state("No approved or allocated requests available for fee settlement.")
            else:
                breq_opts = {
                    f"{r['request_reference']} | {r['hospital']} | {r['blood_group']} {r['component']}": int(r["id"])
                    for _, r in bill_reqs.head(40).iterrows()
                }
                sel_breq = st.selectbox("Select Blood Request", options=list(breq_opts.keys()), key="pay_req_sel")
                sel_req_id = breq_opts[sel_breq]

                # Match any linked transport dispatch for this request
                matched_disp_id = None
                if not dispatches_df.empty:
                    req_ref_code = sel_breq.split(" | ")[0]
                    md = dispatches_df[dispatches_df["request_reference"] == req_ref_code]
                    if not md.empty:
                        matched_disp_id = int(md.iloc[0]["id"])

                est = estimate_service_charges(session, request_id=sel_req_id, dispatch_id=matched_disp_id)
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
                                <strong>PROFORMA INVOICE</strong><br/>{inv_date_str}
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

                with st.form("service_payment_form"):
                    p_method = st.selectbox("Payment Method *", options=PAYMENT_METHODS)
                    p_note = st.text_input("Reference / Billing Note", placeholder="e.g. UPI Ref / Hospital PO #")
                    if st.form_submit_button("Complete Online Settlement", type="primary", width="stretch"):
                        try:
                            pay = record_service_payment(
                                session,
                                request_id=sel_req_id,
                                payment_method=p_method,
                                dispatch_id=matched_disp_id,
                                notes=p_note,
                                actor=actor,
                            )
                            session.commit()
                            st.success(f"Payment {pay.payment_reference} recorded ({pay.payment_status} · Ref: {pay.transaction_ref}).")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            render_validation_error(exc)

        with c_led:
            render_section_title("Settlement Ledger & PDF Receipts")
            render_clean_table(payments_df, hide_columns=["id"], height=330)

            if not payments_df.empty:
                rc_opts = {
                    f"{r['payment_reference']} — {r['hospital']} (INR {r['total_amount']:,.2f})": int(r["id"])
                    for _, r in payments_df.head(30).iterrows()
                }
                r1, r2 = st.columns([2.2, 1.1], vertical_alignment="bottom")
                with r1:
                    sel_rc = st.selectbox("Download Receipt PDF", options=list(rc_opts.keys()), key="pay_rc_sel")
                with r2:
                    pdf_bytes = generate_payment_receipt_pdf(session, rc_opts[sel_rc])
                    st.download_button(
                        "Download PDF Receipt",
                        data=pdf_bytes,
                        file_name=f"{sel_rc.split(' — ')[0]}_invoice.pdf",
                        mime="application/pdf",
                        type="primary",
                        width="stretch",
                    )
