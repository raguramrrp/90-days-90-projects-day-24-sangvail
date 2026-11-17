"""Module 12 — Operational Reports, Multi-Format Exports & Power BI Analytical Pack."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import streamlit as st
from sqlalchemy.orm import Session

from app.components.navigation import render_html, render_page_header
from app.components.tables import render_clean_table, render_kpi_strip, render_section_title
from app.config import EXPORTS_DIR, REPORTS_DIR
from backend.services.report_service import (
    REPORT_CATALOG,
    build_report_dataset,
    dataframe_to_csv_bytes,
    dataframe_to_excel_bytes,
    generate_pdf_report_bytes,
)


def render_reports_page(session: Session, blood_bank_id: Optional[int]) -> None:
    render_page_header(
        "Reports",
        "Reports & Analytical Exports",
        "Generate formatted CSV, Excel, and ReportLab PDF operational reports and Power BI-ready analytical exports. Donor personal details are excluded by default.",
    )

    tab_reports, tab_pbi = st.tabs(["Operational Report Generator", "Power BI Analytical Layer"])

    with tab_reports:
        labels_to_keys = {v: k for k, v in REPORT_CATALOG.items()}
        c_sel, c_period = st.columns([2.2, 1.5])
        with c_sel:
            chosen_title = st.selectbox("Select Report", options=list(labels_to_keys.keys()), key="rep_select")
            report_key = labels_to_keys[chosen_title]
        with c_period:
            period_label = st.text_input("Reporting Period Label", value="Rolling 12 Months / Current Snapshot", key="rep_period")

        bank_filter_note = "All Blood Banks" if blood_bank_id is None else f"Blood Bank ID #{blood_bank_id}"
        title, df, metrics = build_report_dataset(
            session,
            report_key=report_key,
            blood_bank_id=blood_bank_id,
            filters_note=bank_filter_note,
        )

        if metrics:
            render_kpi_strip(
                [{"label": k, "value": v, "meta": "Derived from live DB", "tone": "accent" if i == 0 else ""} for i, (k, v) in enumerate(metrics.items())]
            )

        ts_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        csv_bytes = dataframe_to_csv_bytes(df)
        xlsx_bytes = dataframe_to_excel_bytes(df, sheet_name=report_key)
        pdf_bytes = generate_pdf_report_bytes(
            title=title,
            df=df,
            metrics=metrics,
            period_label=period_label,
            filters_applied=bank_filter_note,
        )

        d1, d2, d3, d4 = st.columns([1.2, 1.2, 1.2, 1.5])
        with d1:
            st.download_button(
                "Download CSV",
                data=csv_bytes,
                file_name=f"sangvail_{report_key}_{ts_slug}.csv",
                mime="text/csv",
                width="stretch",
                type="primary",
            )
        with d2:
            st.download_button(
                "Download Excel (.xlsx)",
                data=xlsx_bytes,
                file_name=f"sangvail_{report_key}_{ts_slug}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        with d3:
            st.download_button(
                "Download PDF Report",
                data=pdf_bytes,
                file_name=f"sangvail_{report_key}_{ts_slug}.pdf",
                mime="application/pdf",
                width="stretch",
            )
        with d4:
            if st.button("Save PDF to reports/", width="stretch", key="btn_save_pdf_local"):
                out_path = REPORTS_DIR / f"sangvail_{report_key}_{ts_slug}.pdf"
                out_path.write_bytes(pdf_bytes)
                st.success(f"Saved to `reports/{out_path.name}`.")

        render_section_title(f"Report Preview — {title} ({len(df):,} rows)")
        render_clean_table(df.head(150), height=390)

    with tab_pbi:
        render_section_title("Power BI Optional Reporting Integration")
        st.write(
            "SANGVAIL runs completely standalone without Power BI Desktop. For organizations wishing to connect "
            "Power BI as an optional executive BI layer, use either the PostgreSQL analytical views listed below "
            "or export clean CSV snapshots directly into `exports/`."
        )

        render_html(
            """
            <div class="sv-panel">
                <strong>PostgreSQL / SQLite Analytical Views</strong>
                <ul style="margin:6px 0 0 18px; font-size:12.5px; color:#202A28;">
                    <li><code>v_current_inventory</code> — Unit-level custody and remaining shelf life</li>
                    <li><code>v_blood_group_availability</code> — Available, reserved, pending, and expired counts</li>
                    <li><code>v_monthly_demand</code> — Monthly requested, fulfilled, and shortfall volume</li>
                    <li><code>v_monthly_utilization</code> — Monthly collections, releases, issues, and wastage</li>
                    <li><code>v_expiry_exposure</code> — Active units annotated with remaining shelf life</li>
                    <li><code>v_request_fulfilment</code> — Hospital-level request status and remaining quantity</li>
                    <li><code>v_data_quality_issues</code> — Automated SQL integrity anomaly feed</li>
                </ul>
            </div>
            """
        )

        if st.button("Export All Power BI CSV Snapshots to exports/", type="primary", key="btn_export_pbi_pack"):
            written = []
            for key in REPORT_CATALOG:
                _, rep_df, _ = build_report_dataset(session, report_key=key, blood_bank_id=blood_bank_id)
                out_csv = EXPORTS_DIR / f"pbi_{key}.csv"
                rep_df.to_csv(out_csv, index=False)
                written.append(out_csv.name)
            st.success(f"Exported {len(written)} clean CSV datasets to `exports/`: {', '.join(written)}")
