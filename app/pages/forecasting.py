"""Modules 9 & 10 — Demand Forecasting & Shortage Planning Intelligence."""

from __future__ import annotations

from typing import Optional
import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from app.components.charts import chart_forecast_series
from app.components.navigation import render_html, render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from app.config import BLOOD_GROUP_NAMES
from backend.repositories.master_repo import get_components
from ml.demand_forecasting import (
    extract_daily_demand_series,
    forecast_series,
    generate_and_persist_all_forecasts,
)
from ml.shortage_analysis import compute_shortage_planning_df


def render_forecasting_page(session: Session, blood_bank_id: Optional[int]) -> None:
    render_page_header(
        "Forecasting",
        "Demand Forecasting & Shortage Planning",
        "Chronologically evaluated demand estimates (Naive, Moving Average, Random Forest) paired with transparent rules-based stock coverage analysis.",
    )

    comps = [c.component_name for c in get_components(session, only_enabled=True)]

    tab_fc, tab_shortage = st.tabs(["Demand Forecasting", "Shortage Planning Intelligence"])

    with tab_fc:
        c1, c2, c3, c4 = st.columns([1.3, 1.8, 1.2, 1.7])
        with c1:
            sel_bg = st.selectbox("Blood Group", options=["All"] + BLOOD_GROUP_NAMES, index=0, key="fc_bg")
        with c2:
            sel_comp = st.selectbox("Component", options=["All"] + comps, index=1 if comps else 0, key="fc_comp")
        with c3:
            horizon = st.selectbox("Forecast Horizon", options=[7, 14, 30], index=1, format_func=lambda d: f"Next {d} days", key="fc_hor")
        with c4:
            model_choice = st.selectbox(
                "Forecasting Method",
                options=["Auto (Best CV RMSE)", "Random Forest Regressor", "Moving Average (7d)", "Seasonal Naive (Lag-7)"],
                key="fc_model",
            )

        series = extract_daily_demand_series(
            session,
            blood_bank_id=blood_bank_id,
            blood_group=sel_bg,
            component_name=sel_comp,
        )
        res = forecast_series(
            series,
            horizon_days=int(horizon),
            model_choice=model_choice,
            save_artifact_name=f"rf_{sel_bg}_{sel_comp}".replace(" ", "_").replace("(", "").replace(")", ""),
        )
        fdf = res["forecast_df"]
        hdf = res["history_df"]
        eval_info = res["evaluation"]

        tot_pred = float(fdf["predicted_demand"].sum()) if not fdf.empty else 0.0
        tot_lo = float(fdf["lower_bound"].sum()) if not fdf.empty else 0.0
        tot_hi = float(fdf["upper_bound"].sum()) if not fdf.empty else 0.0
        best_mae = eval_info.get("best_mae")
        best_rmse = eval_info.get("best_rmse")

        render_kpi_strip(
            [
                {"label": f"Estimated {horizon}-Day Demand", "value": f"{tot_pred:.1f}", "meta": f"Range: {tot_lo:.1f} – {tot_hi:.1f} units", "tone": "accent"},
                {"label": "Selected Method", "value": res["selected_model"], "meta": "Chronological split (no shuffle)", "tone": ""},
                {"label": "Holdout MAE", "value": f"{best_mae:.3f}" if best_mae is not None else "N/A", "meta": "Mean Absolute Error (units/day)", "tone": ""},
                {"label": "Holdout RMSE", "value": f"{best_rmse:.3f}" if best_rmse is not None else "N/A", "meta": "Root Mean Squared Error", "tone": ""},
                {"label": "Data Coverage", "value": f"{len(hdf)} days", "meta": res["data_coverage"], "tone": ""},
            ]
        )

        st.info(
            f"**Planning Interpretation Note:** {res['limitation_note']} "
            "Predictions are planning estimates and never guaranteed future requirements."
        )

        st.plotly_chart(
            chart_forecast_series(hdf, fdf, f"Historical Demand & {horizon}-Day Forecast ({sel_bg} · {sel_comp})"),
            width="stretch",
        )

        col_ev, col_daily = st.columns([1.3, 1.7])
        with col_ev:
            render_section_title("Chronological Model Evaluation")
            st.caption(eval_info.get("reason", ""))
            if eval_info.get("metrics"):
                render_clean_table(pd.DataFrame(eval_info["metrics"]), height=180)
            else:
                render_empty_state("Insufficient historical depth for multi-model comparison; Moving Average baseline applied.")

            if st.button("Refresh & Persist All Group/Component Forecasts", type="primary", key="btn_refresh_fc"):
                with st.spinner("Running chronological forecasting across all blood groups and components..."):
                    summary_df, _ = generate_and_persist_all_forecasts(
                        session,
                        horizon_days=int(horizon),
                        blood_bank_id=blood_bank_id,
                        model_choice=model_choice,
                    )
                    session.commit()
                    st.success(f"Updated and persisted {len(summary_df)} forecast series into database.")
                    st.rerun()

        with col_daily:
            render_section_title(f"Daily Forecast Schedule (Next {horizon} Days)")
            render_clean_table(fdf, height=250)

        # Consolidated Forecast vs Stock Planning Table
        render_section_title(f"Forecast vs. Current Eligible Stock ({horizon}-Day Horizon)")
        short_df = compute_shortage_planning_df(session, blood_bank_id=blood_bank_id, horizon_days=int(horizon))
        if not short_df.empty:
            plan_view = short_df[["blood_group", "component", "forecast_demand", "eligible_stock", "minimum_stock", "planning_status"]]
            render_clean_table(plan_view, height=340)

    with tab_shortage:
        render_section_title("Shortage Planning Intelligence (Transparent Rules Engine)")
        st.caption(
            "Planning statuses (Critical, High, Moderate, Stable) are operational inventory indicators derived from "
            "eligible stock, open requests, coverage days, near-expiry stock, forecast demand, and configured minimum floors. "
            "They are not clinical risk classifications."
        )

        sh_hor = st.selectbox("Planning Horizon", [7, 14, 30], index=1, format_func=lambda d: f"{d} days", key="sh_hor")
        sh_df = compute_shortage_planning_df(session, blood_bank_id=blood_bank_id, horizon_days=int(sh_hor))

        if sh_df.empty:
            render_empty_state("No inventory planning pairs available.")
        else:
            crit_n = int((sh_df["planning_status"] == "Critical").sum())
            high_n = int((sh_df["planning_status"] == "High").sum())
            mod_n = int((sh_df["planning_status"] == "Moderate").sum())
            stab_n = int((sh_df["planning_status"] == "Stable").sum())

            render_kpi_strip(
                [
                    {"label": "Critical Planning Pairs", "value": crit_n, "meta": "Immediate replenishment review", "tone": "critical" if crit_n else ""},
                    {"label": "High Priority Pairs", "value": high_n, "meta": "Monitor intake closely", "tone": "warning" if high_n else ""},
                    {"label": "Moderate Pairs", "value": mod_n, "meta": "Watch near-term demand", "tone": ""},
                    {"label": "Stable Pairs", "value": stab_n, "meta": "Above configured floor", "tone": "accent"},
                ]
            )

            status_filter = st.multiselect(
                "Filter Planning Status",
                options=["Critical", "High", "Moderate", "Stable"],
                default=["Critical", "High", "Moderate", "Stable"],
                key="sh_status_f",
            )
            filtered_sh = sh_df[sh_df["planning_status"].isin(status_filter)] if status_filter else sh_df
            render_clean_table(
                filtered_sh[
                    [
                        "blood_group",
                        "component",
                        "eligible_stock",
                        "open_requests",
                        "avg_daily_demand",
                        "coverage_days",
                        "minimum_stock",
                        "forecast_demand",
                        "planning_status",
                    ]
                ],
                height=360,
            )

            render_section_title("Explainability — Why Warnings Were Generated")
            flagged = filtered_sh[filtered_sh["planning_status"].isin(["Critical", "High"])].head(10)
            if flagged.empty:
                render_empty_state("No Critical or High shortage planning alerts under current filters.")
            else:
                for _, row in flagged.iterrows():
                    cls = "critical" if row["planning_status"] == "Critical" else "warning"
                    render_html(
                        f"""
                        <div class="sv-alert-row {cls}">
                            <div class="sv-alert-title">
                                <span class="sv-badge {cls}">{row['planning_status']}</span>
                                <span class="sv-bg-pill">{row['blood_group']}</span>
                                {row['component']} (Score: {row['planning_score']}/100)
                            </div>
                            <div class="sv-alert-detail">{row['explanation']}</div>
                        </div>
                        """
                    )
