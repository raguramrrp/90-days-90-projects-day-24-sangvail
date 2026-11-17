"""Module 11 — Operational Data Quality Centre & ETL Run Audit."""

from __future__ import annotations

from typing import Optional
import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.components.navigation import render_page_header
from app.components.tables import render_clean_table, render_empty_state, render_kpi_strip, render_section_title
from backend.models import ETLRunLog
from backend.services.data_quality_service import (
    remediate_expired_released_unit,
    remediate_unreleased_quarantine_unit,
    run_data_quality_checks,
)


def render_data_quality_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header(
        "Data Quality",
        "Data Quality Centre",
        "Automated operational integrity auditing across unit custody, screening clearance, request allocations, and transaction history.",
    )

    dq = run_data_quality_checks(session, blood_bank_id=blood_bank_id)
    score = dq["overall_score"]
    score_tone = "accent" if score >= 95 else ("warning" if score >= 80 else "critical")

    render_kpi_strip(
        [
            {"label": "Overall Quality Score", "value": f"{score:.1f}%", "meta": "Derived from live 14-check suite", "tone": score_tone},
            {"label": "Records Audited", "value": f"{dq['total_records_checked']:,}", "meta": "Units, requests & transactions", "tone": ""},
            {"label": "Passed Checks", "value": f"{dq['passed_checks']} / {dq['total_checks']}", "meta": "Zero anomalies detected", "tone": "accent"},
            {"label": "Failed Checks", "value": str(dq["failed_checks"]), "meta": "Checks with >= 1 exception", "tone": "critical" if dq["failed_checks"] else ""},
            {"label": "Critical Errors", "value": str(dq["critical_error_count"]), "meta": "Immediate governance action", "tone": "critical" if dq["critical_error_count"] else ""},
            {"label": "Warnings", "value": str(dq["warning_count"]), "meta": "Audit review recommended", "tone": "warning" if dq["warning_count"] else ""},
        ]
    )

    tab_suite, tab_issues, tab_etl = st.tabs(
        ["14-Check Integrity Matrix", "Failed Record Inspection & Remediation", "ETL Execution Reports"]
    )

    with tab_suite:
        render_section_title("Validation Check Summary")
        render_clean_table(dq["checks_df"], height=460)

    with tab_issues:
        issues_df = dq["issues_df"]
        if issues_df.empty:
            render_empty_state(
                "All 14 data integrity checks passed with zero record-level discrepancies. "
                "Records are never silently altered; any future discrepancy will appear here for controlled remediation."
            )
        else:
            render_section_title("Individual Record Exceptions")
            render_clean_table(issues_df, height=300)

            render_section_title("Controlled Remediation Workflows (Audit Logged)")
            exp_issues = issues_df[issues_df["check_code"] == "DQ-14"]
            if not exp_issues.empty:
                sel_exp = st.selectbox(
                    "Expired unit still marked Released (DQ-14)",
                    options=exp_issues["entity_id"].tolist(),
                    key="dq_rem_exp_sel",
                )
                if st.button("Transition Selected Unit to Expired (Audited)", type="primary", key="dq_rem_exp_btn"):
                    msg = remediate_expired_released_unit(session, sel_exp, actor=actor)
                    session.commit()
                    st.success(msg)
                    st.rerun()

            unrel_issues = issues_df[issues_df["check_code"] == "DQ-06"]
            if not unrel_issues.empty:
                sel_unrel = st.selectbox(
                    "Uncleared unit marked Released (DQ-06)",
                    options=unrel_issues["entity_id"].tolist(),
                    key="dq_rem_unrel_sel",
                )
                if st.button("Move Selected Unit to Quarantine (Audited)", type="primary", key="dq_rem_unrel_btn"):
                    msg = remediate_unreleased_quarantine_unit(session, sel_unrel, actor=actor)
                    session.commit()
                    st.success(msg)
                    st.rerun()

    with tab_etl:
        render_section_title("Recorded ETL Pipeline Runs")
        logs = session.scalars(select(ETLRunLog).order_by(ETLRunLog.created_at.desc()).limit(30)).all()
        if not logs:
            render_empty_state("No ETL execution runs logged yet.")
        else:
            etl_df = pd.DataFrame(
                [
                    {
                        "run_reference": r.run_reference,
                        "source_name": r.source_name,
                        "extracted": r.records_extracted,
                        "accepted": r.records_accepted,
                        "rejected": r.records_rejected,
                        "duplicates": r.duplicate_records,
                        "elapsed_sec": r.execution_seconds,
                        "status": r.status,
                        "summary": r.validation_summary,
                        "timestamp": r.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for r in logs
                ]
            )
            render_clean_table(etl_df, height=340)
