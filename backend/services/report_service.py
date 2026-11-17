"""Report generation service: CSV, Excel, and ReportLab PDF exports (PII-safe by default)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.config import APP_NAME, SYNTHETIC_DATA_DISCLAIMER
from backend.services.analytics_service import (
    get_collection_vs_utilization_monthly,
    get_demand_intelligence_bundle,
)
from backend.services.data_quality_service import run_data_quality_checks
from backend.services.donation_service import list_donations_df
from backend.services.expiry_service import get_expiry_monitor_df, get_wastage_history_df
from backend.services.inventory_service import get_stock_by_group_and_component, list_inventory_df
from backend.services.request_service import list_requests_df
from ml.demand_forecasting import get_saved_forecasts_df


REPORT_CATALOG = {
    "current_inventory": "Current Inventory Report",
    "blood_group_availability": "Blood-Group Availability Report",
    "donation_collection": "Donation Collection Report (De-identified)",
    "request_fulfilment": "Blood Request Fulfilment Report",
    "expiry_wastage": "Expiry & Wastage Report",
    "monthly_utilization": "Monthly Utilization Report",
    "demand_forecasting": "Demand Forecasting Report",
    "data_quality": "Data Quality Audit Report",
}


def build_report_dataset(
    session: Session,
    report_key: str,
    blood_bank_id: Optional[int] = None,
    filters_note: str = "All active records",
) -> tuple[str, pd.DataFrame, dict[str, str]]:
    """Build report title, clean DataFrame (no donor PII by default), and key summary metrics."""
    if report_key == "current_inventory":
        df = list_inventory_df(session, blood_bank_id=blood_bank_id)
        if not df.empty:
            df = df[
                [
                    "unit_reference",
                    "blood_group",
                    "component",
                    "collection_date",
                    "expiry_date",
                    "remaining_days",
                    "screening_status",
                    "inventory_status",
                    "storage_location",
                ]
            ]
        metrics = {
            "Total Units": str(len(df)),
            "Released Units": str(int((df["inventory_status"] == "Released").sum())) if not df.empty else "0",
            "Reserved Units": str(int((df["inventory_status"] == "Reserved").sum())) if not df.empty else "0",
        }
    elif report_key == "blood_group_availability":
        df = get_stock_by_group_and_component(session, blood_bank_id=blood_bank_id)
        metrics = {
            "Group-Component Pairs": str(len(df)),
            "Total Eligible Available": str(int(df["available"].sum())) if not df.empty else "0",
            "Total Reserved": str(int(df["reserved"].sum())) if not df.empty else "0",
        }
    elif report_key == "donation_collection":
        df = list_donations_df(session, blood_bank_id=blood_bank_id)
        # Never export donor personal name or contact by default
        if not df.empty:
            df = df[
                [
                    "donation_reference",
                    "donor_reference",
                    "blood_group",
                    "donation_date",
                    "collection_location",
                    "collection_type",
                    "collected_quantity",
                    "collection_status",
                    "units_produced",
                ]
            ]
        metrics = {
            "Total Donations": str(len(df)),
            "Completed": str(int((df["collection_status"] == "Completed").sum())) if not df.empty else "0",
            "Rejected": str(int((df["collection_status"] == "Rejected").sum())) if not df.empty else "0",
        }
    elif report_key == "request_fulfilment":
        df = list_requests_df(session, blood_bank_id=blood_bank_id)
        if not df.empty:
            df = df[
                [
                    "request_reference",
                    "hospital",
                    "blood_group",
                    "component",
                    "required_quantity",
                    "allocated_quantity",
                    "remaining_quantity",
                    "urgency",
                    "request_date",
                    "status",
                ]
            ]
        tot_req = int(df["required_quantity"].sum()) if not df.empty else 0
        tot_al = int(df["allocated_quantity"].sum()) if not df.empty else 0
        rate = f"{(tot_al / tot_req * 100):.1f}%" if tot_req else "0.0%"
        metrics = {
            "Total Requests": str(len(df)),
            "Requested Units": str(tot_req),
            "Allocated Units": str(tot_al),
            "Fulfilment Rate": rate,
        }
    elif report_key == "expiry_wastage":
        exp_df = get_expiry_monitor_df(session, blood_bank_id=blood_bank_id)
        wast_df = get_wastage_history_df(session, blood_bank_id=blood_bank_id)
        df = wast_df if not wast_df.empty else exp_df
        metrics = {
            "Historical Wastage Events": str(len(wast_df)),
            "Active Critical/Approaching": str(
                int(exp_df["expiry_category"].isin(["Critical Window", "Approaching Expiry"]).sum())
            )
            if not exp_df.empty
            else "0",
        }
    elif report_key == "monthly_utilization":
        df = get_collection_vs_utilization_monthly(session, blood_bank_id=blood_bank_id, months=12)
        metrics = {
            "Months Covered": str(len(df)),
            "Total Collected": str(int(df["collected"].sum())) if not df.empty else "0",
            "Total Issued": str(int(df["issued"].sum())) if not df.empty else "0",
            "Total Wastage": str(int(df["wastage"].sum())) if not df.empty else "0",
        }
    elif report_key == "demand_forecasting":
        df = get_saved_forecasts_df(session)
        metrics = {
            "Forecast Rows": str(len(df)),
            "Total Predicted Units": f"{df['predicted_demand'].sum():.1f}" if not df.empty else "0.0",
        }
    elif report_key == "data_quality":
        dq = run_data_quality_checks(session, blood_bank_id=blood_bank_id)
        df = dq["checks_df"]
        metrics = {
            "Quality Score": f"{dq['overall_score']}%",
            "Records Checked": str(dq["total_records_checked"]),
            "Passed Checks": f"{dq['passed_checks']}/{dq['total_checks']}",
            "Critical Errors": str(dq["critical_error_count"]),
        }
    else:
        raise ValueError(f"Unknown report key '{report_key}'.")

    title = REPORT_CATALOG[report_key]
    return title, df, metrics


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Report") -> bytes:
    buf = io.BytesIO()
    safe_sheet = sheet_name[:31].replace("/", "-").replace(":", "-")
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=safe_sheet)
        ws = writer.sheets[safe_sheet]
        for idx, col in enumerate(df.columns):
            if not df.empty:
                col_max = int(df[col].astype("object").fillna("").astype(str).str.len().max())
            else:
                col_max = 10
            max_len = max(len(str(col)), col_max)
            ws.set_column(idx, idx, min(max_len + 3, 36))
    return buf.getvalue()


def generate_pdf_report_bytes(
    title: str,
    df: pd.DataFrame,
    metrics: dict[str, str],
    period_label: str = "Last 12 Months / Current Snapshot",
    filters_applied: str = "Default operational filters",
    max_rows: int = 80,
) -> bytes:
    """Render a clean operational PDF report using ReportLab."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SVTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#202A28"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SVSub",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#75807C"),
        spaceAfter=10,
    )
    disclaimer_style = ParagraphStyle(
        "SVDisclaimer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#75807C"),
        backColor=colors.HexColor("#EDF1ED"),
        borderPadding=6,
    )

    generated_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    elements = [
        Paragraph(f"{APP_NAME} — {title}", title_style),
        Paragraph(
            f"<b>Reporting Period:</b> {period_label} &nbsp;|&nbsp; "
            f"<b>Generated:</b> {generated_ts} &nbsp;|&nbsp; "
            f"<b>Filters:</b> {filters_applied}",
            subtitle_style,
        ),
    ]

    if metrics:
        metric_items = list(metrics.items())
        metric_headers = [k for k, _ in metric_items]
        metric_vals = [v for _, v in metric_items]
        kpi_table = Table([metric_headers, metric_vals], hAlign="LEFT")
        kpi_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF1ED")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#75807C")),
                    ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#202A28")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("FONTSIZE", (0, 1), (-1, 1), 11),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E3E8E4")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        elements.append(kpi_table)
        elements.append(Spacer(1, 12))

    if df.empty:
        elements.append(Paragraph("No records matched the selected filters for this report.", styles["Normal"]))
    else:
        display_df = df.head(max_rows).copy()
        headers = [str(c).replace("_", " ").title() for c in display_df.columns]
        body = [[str(v)[:34] for v in row] for row in display_df.values.tolist()]
        table_data = [headers] + body
        data_table = Table(table_data, repeatRows=1, hAlign="LEFT")
        data_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#315F52")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("FONTSIZE", (0, 1), (-1, -1), 7.5),
                    ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#202A28")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F6F4")]),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3E8E4")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        elements.append(data_table)
        if len(df) > max_rows:
            elements.append(Spacer(1, 6))
            elements.append(
                Paragraph(
                    f"Showing first {max_rows} of {len(df)} total rows. Export CSV or Excel for the complete table.",
                    subtitle_style,
                )
            )

    elements.append(Spacer(1, 14))
    elements.append(Paragraph(SYNTHETIC_DATA_DISCLAIMER, disclaimer_style))
    doc.build(elements)
    return buf.getvalue()
