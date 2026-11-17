"""Module 8 — Demand Intelligence & Evidence-Based Operational Observations."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import streamlit as st
from sqlalchemy.orm import Session

from app.components.charts import (
    chart_bar_simple,
    chart_collection_vs_utilization,
    chart_demand_heatmap,
    chart_line_simple,
)
from app.components.filters import render_blood_group_component_filters
from app.components.navigation import render_html, render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from app.config import REQUEST_STATUSES, REQUEST_URGENCIES
from backend.repositories.master_repo import get_components, get_hospitals
from backend.services.analytics_service import (
    get_collection_vs_utilization_monthly,
    get_demand_intelligence_bundle,
)


def render_demand_intelligence_page(session: Session, blood_bank_id: Optional[int]) -> None:
    render_page_header(
        "Intelligence",
        "Demand Intelligence",
        "Analyze historical request patterns, component utilization, fulfilment gaps, and evidence-backed operational observations.",
    )

    comps = [c.component_name for c in get_components(session)]
    hospitals = [h.hospital_name for h in get_hospitals(session)]

    f1, f2, f3 = st.columns([1.2, 1.2, 2.6])
    with f1:
        start_dt = st.date_input("Start Date", value=date.today() - timedelta(days=365), key="di_start")
    with f2:
        end_dt = st.date_input("End Date", value=date.today(), key="di_end")
    with f3:
        sel_bg, sel_comp = render_blood_group_component_filters(comps, "di")

    f4, f5, f6 = st.columns(3)
    with f4:
        sel_hosp = st.selectbox("Hospital", options=["All"] + hospitals, key="di_hosp")
    with f5:
        sel_urg = st.multiselect("Urgency", options=REQUEST_URGENCIES, default=[], key="di_urg", placeholder="All urgencies")
    with f6:
        sel_st = st.multiselect("Request Status", options=REQUEST_STATUSES, default=[], key="di_status", placeholder="All statuses")

    bundle = get_demand_intelligence_bundle(
        session,
        blood_bank_id=blood_bank_id,
        start_date=start_dt,
        end_date=end_dt,
        blood_groups=sel_bg or None,
        components=sel_comp or None,
        hospital_name=sel_hosp,
        urgencies=sel_urg or None,
        statuses=sel_st or None,
    )
    kpis = bundle["kpis"]
    render_kpi_strip(
        [
            {"label": "Total Requested Units", "value": f"{kpis['total_requested']:,}", "meta": "Filtered valid requests", "tone": "accent"},
            {"label": "Total Fulfilled Units", "value": f"{kpis['total_fulfilled']:,}", "meta": "Allocated / issued volume", "tone": ""},
            {"label": "Unfulfilled Shortfall", "value": f"{kpis['unfulfilled_units']:,}", "meta": "Demand gap in period", "tone": "warning" if kpis["unfulfilled_units"] else ""},
            {"label": "Fulfilment Rate", "value": f"{kpis['fulfilment_rate_pct']:.1f}%", "meta": "Fulfilled / requested", "tone": "accent" if kpis["fulfilment_rate_pct"] >= 80 else "warning"},
        ]
    )

    if bundle["requests_df"].empty:
        render_empty_state("No demand records match the selected filters.")
        return

    # Evidence-Based Insights (derived strictly from live query results)
    render_section_title("Evidence-Based Operational Observations")
    insights = bundle["insights"]
    if not insights:
        render_empty_state("Insufficient period depth under current filters to compute comparative observations.")
    else:
        for ins in insights:
            render_html(
                f"""
                <div class="sv-alert-row">
                    <div class="sv-alert-title">{ins['observation']}</div>
                    <div class="sv-alert-detail">
                        <strong>Period:</strong> {ins['period']} &nbsp;|&nbsp;
                        <strong>Metric:</strong> {ins['supporting_metric']} &nbsp;|&nbsp;
                        <strong>Baseline:</strong> {ins['comparison_baseline']} &nbsp;|&nbsp;
                        <strong>Coverage:</strong> {ins['data_coverage']}
                    </div>
                </div>
                """
            )

    # Analytical Charts
    render_section_title("Demand & Utilization Trends")
    r1_l, r1_r = st.columns(2)
    with r1_l:
        st.plotly_chart(
            chart_line_simple(bundle["monthly_df"], "month", "requested_units", "Monthly Blood Demand Trend", y_title="Requested Units"),
            width="stretch",
        )
    with r1_r:
        st.plotly_chart(
            chart_bar_simple(bundle["by_group_df"], "blood_group", "requested_units", "Blood-Group Demand Comparison"),
            width="stretch",
        )

    r2_l, r2_r = st.columns(2)
    with r2_l:
        st.plotly_chart(
            chart_bar_simple(bundle["by_component_df"], "component", "requested_units", "Component Utilization & Demand"),
            width="stretch",
        )
    with r2_r:
        util_df = get_collection_vs_utilization_monthly(session, blood_bank_id=blood_bank_id, months=12)
        st.plotly_chart(chart_collection_vs_utilization(util_df), width="stretch")

    r3_l, r3_r = st.columns(2)
    with r3_l:
        st.plotly_chart(
            chart_line_simple(bundle["monthly_df"], "month", "fulfilment_rate_pct", "Monthly Request Fulfilment Rate (%)", y_title="Fulfilment %"),
            width="stretch",
        )
    with r3_r:
        st.plotly_chart(chart_demand_heatmap(bundle["heatmap_df"]), width="stretch")

    render_section_title("Summary by Blood Group")
    render_clean_table(bundle["by_group_df"], height=260)
