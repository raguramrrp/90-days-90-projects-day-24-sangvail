"""Module 1 — Decision-oriented Overview Workstation."""

from __future__ import annotations

from typing import Optional
import streamlit as st
from sqlalchemy.orm import Session

from app.components.charts import (
    chart_collection_vs_utilization,
    chart_expiry_timeline,
    chart_inventory_by_blood_group,
    chart_monthly_request_volume,
)
from app.components.navigation import navigate_to, render_html, render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from app.config import BLOOD_GROUP_NAMES
from backend.services.analytics_service import (
    get_collection_vs_utilization_monthly,
    get_demand_intelligence_bundle,
    get_needs_attention_alerts,
    get_overview_kpis,
    get_recent_activity_df,
)
from backend.services.expiry_service import get_expiry_monitor_df
from backend.services.inventory_service import get_stock_by_group_and_component


def render_overview_page(session: Session, blood_bank_id: Optional[int]) -> None:
    render_page_header(
        "Overview",
        "Operations Overview",
        "Real-time unit-level inventory visibility, actionable operational exceptions, and recent custody activity.",
    )

    kpis = get_overview_kpis(session, blood_bank_id=blood_bank_id)
    render_kpi_strip(
        [
            {
                "label": "Released Units Available",
                "value": f"{kpis['total_released_available']:,}",
                "meta": f"{kpis['reconciliation']['total_reserved']:,} reserved (excluded)",
                "tone": "accent",
            },
            {
                "label": "Pending Screening Units",
                "value": f"{kpis['pending_screening_units']:,}",
                "meta": f"{kpis['reconciliation']['quarantined']:,} quarantined",
                "tone": "warning" if kpis["pending_screening_units"] > 15 else "",
            },
            {
                "label": "Active Blood Requests",
                "value": f"{kpis['active_blood_requests']:,}",
                "meta": "Submitted through Allocated",
                "tone": "",
            },
            {
                "label": "Units Approaching Expiry",
                "value": f"{kpis['units_approaching_expiry']:,}",
                "meta": "Within component warning window",
                "tone": "critical" if kpis["units_approaching_expiry"] > 10 else "warning",
            },
            {
                "label": "Unfulfilled Requests",
                "value": f"{kpis['unfulfilled_requests']:,}",
                "meta": "Open requests with remaining qty",
                "tone": "critical" if kpis["unfulfilled_requests"] > 5 else "warning",
            },
            {
                "label": "Units Issued This Month",
                "value": f"{kpis['units_issued_this_month']:,}",
                "meta": "Handed over to hospitals",
                "tone": "accent",
            },
        ]
    )

    # Available Stock by Blood Group (All 8 ABO/Rh Groups Separately)
    stock_df = get_stock_by_group_and_component(session, blood_bank_id=blood_bank_id)
    render_section_title("Available Stock by Blood Group")
    group_totals: dict[str, dict[str, int]] = {
        bg: {"available": 0, "reserved": 0, "pending": 0} for bg in BLOOD_GROUP_NAMES
    }
    if not stock_df.empty:
        agg_bg = stock_df.groupby("blood_group", as_index=False)[["available", "reserved", "pending_screening"]].sum()
        for _, row in agg_bg.iterrows():
            bg_key = row["blood_group"]
            if bg_key in group_totals:
                group_totals[bg_key] = {
                    "available": int(row["available"]),
                    "reserved": int(row["reserved"]),
                    "pending": int(row["pending_screening"]),
                }

    bg_tiles = []
    for bg in BLOOD_GROUP_NAMES:
        st_info = group_totals[bg]
        avail_n = st_info["available"]
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

    # Needs Attention Section
    render_section_title("Needs Attention")
    alerts = get_needs_attention_alerts(session, blood_bank_id=blood_bank_id)
    if not alerts:
        render_empty_state("No active operational exceptions detected for the selected blood bank.")
    else:
        for idx, alert in enumerate(alerts[:8]):
            sev = alert["severity"]
            cls = "critical" if sev == "Critical" else "warning"
            c_msg, c_btn = st.columns([6.5, 1.3], vertical_alignment="center")
            bg_pill = (
                f'<span class="sv-bg-pill">{alert["filter_blood_group"]}</span>'
                if alert.get("filter_blood_group")
                else ""
            )
            with c_msg:
                render_html(
                    f"""
                    <div class="sv-alert-row {cls}">
                        <div class="sv-alert-title">
                            <span class="sv-badge {cls}">{alert['category']}</span>{bg_pill}{alert['title']}
                        </div>
                        <div class="sv-alert-detail">{alert['detail']}</div>
                    </div>
                    """
                )
            with c_btn:
                if st.button(f"Inspect ->", key=f"ov_alert_{idx}", width="stretch"):
                    navigate_to(
                        alert["target_page"],
                        blood_group=alert.get("filter_blood_group"),
                        component=alert.get("filter_component"),
                    )

    # 4 Core Operational Visualisations
    render_section_title("Operational Analytics")
    util_df = get_collection_vs_utilization_monthly(session, blood_bank_id=blood_bank_id, months=12)
    demand_bundle = get_demand_intelligence_bundle(session, blood_bank_id=blood_bank_id)
    exp_df = get_expiry_monitor_df(session, blood_bank_id=blood_bank_id)

    row1_l, row1_r = st.columns(2, gap="large")
    with row1_l:
        st.plotly_chart(chart_inventory_by_blood_group(stock_df), width="stretch")
    with row1_r:
        st.plotly_chart(chart_collection_vs_utilization(util_df), width="stretch")

    row2_l, row2_r = st.columns(2, gap="large")
    with row2_l:
        st.plotly_chart(chart_monthly_request_volume(demand_bundle["monthly_df"]), width="stretch")
    with row2_r:
        st.plotly_chart(chart_expiry_timeline(exp_df), width="stretch")

    # Recent Activity Log
    render_section_title("Recent Inventory Activity")
    f1, f2, f3 = st.columns([2, 2, 1.2])
    with f1:
        act_filter = st.multiselect(
            "Activity Type",
            options=["COLLECTED", "RELEASED", "RESERVED", "ISSUED", "EXPIRED", "DISCARDED", "QUARANTINED", "REJECTED", "ALLOCATION_REVERSED"],
            default=[],
            key="ov_act_type",
            placeholder="All activities",
        )
    with f2:
        bg_filter = st.multiselect(
            "Blood Group",
            options=BLOOD_GROUP_NAMES,
            default=[],
            key="ov_act_bg",
            placeholder="All blood groups",
        )
    with f3:
        limit = st.selectbox("Rows", [20, 50, 100], index=0, key="ov_act_limit")

    activity_df = get_recent_activity_df(
        session,
        blood_bank_id=blood_bank_id,
        limit=int(limit),
        activity_types=act_filter or None,
        blood_groups=bg_filter or None,
    )
    if not activity_df.empty:
        activity_df["timestamp"] = activity_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    render_clean_table(activity_df, hide_columns=["transaction_code"], height=300)
