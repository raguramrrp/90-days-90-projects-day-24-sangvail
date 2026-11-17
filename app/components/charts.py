"""Harmonious clinical-grade Plotly charts for SANGVAIL."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.config import PALETTE

CLINICAL_TEAL = "#0F766E"
CLINICAL_CYAN = "#0284C7"
CLINICAL_AMBER = "#D97706"
CLINICAL_CRIMSON = "#E11D48"
CLINICAL_SLATE = "#64748B"

CHART_SEQUENCE = [
    CLINICAL_TEAL,
    CLINICAL_CYAN,
    CLINICAL_AMBER,
    CLINICAL_SLATE,
    CLINICAL_CRIMSON,
    "#0D9488",
]


def _apply_layout(fig: go.Figure, title: str = "", height: int = 320, y_title: str = "", x_title: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=14.5, color="#0F172A", family="Plus Jakarta Sans, Inter, sans-serif"),
            x=0.01,
            xanchor="left",
        ),
        height=height,
        margin=dict(l=14, r=14, t=44 if title else 18, b=30),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Inter, sans-serif", size=12, color="#0F172A"),
        hoverlabel=dict(
            bgcolor="#FFFFFF",
            bordercolor="#E2E8F0",
            font=dict(size=12, family="Inter, sans-serif", color="#0F172A"),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            font=dict(size=11.5, color="#475569"),
            title=None,
        ),
        xaxis=dict(
            title=x_title,
            showgrid=False,
            linecolor="#E2E8F0",
            tickfont=dict(size=11.5, color="#64748B"),
        ),
        yaxis=dict(
            title=y_title,
            gridcolor="#E2E8F0",
            griddash="dot",
            zerolinecolor="#E2E8F0",
            tickfont=dict(size=11.5, color="#64748B"),
        ),
    )
    return fig


def chart_inventory_by_blood_group(stock_df: pd.DataFrame) -> go.Figure:
    if stock_df.empty:
        return _apply_layout(go.Figure(), "Inventory Distribution by Blood Group")
    agg = stock_df.groupby("blood_group", as_index=False)[["available", "reserved", "pending_screening"]].sum()
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Available (Released)", x=agg["blood_group"], y=agg["available"], marker_color=CLINICAL_TEAL))
    fig.add_trace(go.Bar(name="Reserved", x=agg["blood_group"], y=agg["reserved"], marker_color=CLINICAL_CYAN))
    fig.add_trace(go.Bar(name="Pending Screening", x=agg["blood_group"], y=agg["pending_screening"], marker_color=CLINICAL_AMBER))
    fig.update_layout(barmode="stack")
    return _apply_layout(fig, "Inventory Distribution by Blood Group", height=310, y_title="Units")


def chart_collection_vs_utilization(monthly_df: pd.DataFrame) -> go.Figure:
    if monthly_df.empty:
        return _apply_layout(go.Figure(), "Collection vs. Utilization Over Time")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=monthly_df["month"], y=monthly_df["collected"], name="Collected", mode="lines+markers", line=dict(color=CLINICAL_TEAL, width=2.4)))
    fig.add_trace(go.Scatter(x=monthly_df["month"], y=monthly_df["issued"], name="Issued", mode="lines+markers", line=dict(color=CLINICAL_CYAN, width=2.4)))
    fig.add_trace(go.Bar(x=monthly_df["month"], y=monthly_df["wastage"], name="Expired/Discarded", marker_color="#FDE68A", opacity=0.85))
    return _apply_layout(fig, "Collection vs. Utilization Over Time", height=310, y_title="Units")


def chart_monthly_request_volume(monthly_df: pd.DataFrame) -> go.Figure:
    if monthly_df.empty:
        return _apply_layout(go.Figure(), "Monthly Request Volume & Fulfilment")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=monthly_df["month"], y=monthly_df["fulfilled_units"], name="Fulfilled", marker_color=CLINICAL_TEAL))
    fig.add_trace(go.Bar(x=monthly_df["month"], y=monthly_df["unfulfilled_units"], name="Unfulfilled", marker_color=CLINICAL_AMBER))
    fig.update_layout(barmode="stack")
    return _apply_layout(fig, "Monthly Request Volume", height=310, y_title="Units")


def chart_expiry_timeline(expiry_df: pd.DataFrame) -> go.Figure:
    if expiry_df.empty:
        return _apply_layout(go.Figure(), "Active Inventory Expiry Timeline")
    active = expiry_df[expiry_df["inventory_status"].isin(["Released", "Reserved"])].copy()
    if active.empty:
        return _apply_layout(go.Figure(), "Active Inventory Expiry Timeline")

    def _bucket(d: int) -> str:
        if d < 0:
            return "Expired"
        if d <= 3:
            return "0–3 days"
        if d <= 7:
            return "4–7 days"
        if d <= 14:
            return "8–14 days"
        if d <= 30:
            return "15–30 days"
        return ">30 days"

    order = ["Expired", "0–3 days", "4–7 days", "8–14 days", "15–30 days", ">30 days"]
    color_map = {
        "Expired": CLINICAL_CRIMSON,
        "0–3 days": CLINICAL_CRIMSON,
        "4–7 days": CLINICAL_AMBER,
        "8–14 days": CLINICAL_SLATE,
        "15–30 days": CLINICAL_CYAN,
        ">30 days": CLINICAL_TEAL,
    }
    active["bucket"] = active["remaining_days"].apply(_bucket)
    counts = active["bucket"].value_counts().reindex(order, fill_value=0).reset_index()
    counts.columns = ["bucket", "units"]
    fig = go.Figure(
        go.Bar(
            x=counts["bucket"],
            y=counts["units"],
            marker_color=[color_map[b] for b in counts["bucket"]],
            text=counts["units"],
            textposition="outside",
        )
    )
    return _apply_layout(fig, "Active Inventory Expiry Timeline", height=310, y_title="Units")


def chart_demand_heatmap(heatmap_df: pd.DataFrame) -> go.Figure:
    if heatmap_df.empty:
        return _apply_layout(go.Figure(), "Blood-Group Demand Heatmap")
    fig = go.Figure(
        go.Heatmap(
            z=heatmap_df.values,
            x=list(heatmap_df.columns),
            y=list(heatmap_df.index),
            colorscale=[[0.0, "#F8FAFC"], [0.5, "#5EEAD4"], [1.0, CLINICAL_TEAL]],
            hoverongaps=False,
        )
    )
    return _apply_layout(fig, "Monthly Demand Heatmap by Blood Group", height=330)


def chart_forecast_series(history_df: pd.DataFrame, forecast_df: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    if not history_df.empty:
        recent = history_df.tail(90)
        fig.add_trace(
            go.Scatter(
                x=recent["date"],
                y=recent["actual_demand"],
                name="Historical Actual Demand",
                mode="lines",
                line=dict(color="#334155", width=1.9),
            )
        )
    if not forecast_df.empty:
        fig.add_trace(
            go.Scatter(
                x=list(forecast_df["forecast_date"]) + list(forecast_df["forecast_date"])[::-1],
                y=list(forecast_df["upper_bound"]) + list(forecast_df["lower_bound"])[::-1],
                fill="toself",
                fillcolor="rgba(15, 118, 110, 0.14)",
                line=dict(color="rgba(255,255,255,0)"),
                name="Uncertainty Range",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=forecast_df["forecast_date"],
                y=forecast_df["predicted_demand"],
                name="Forecasted Demand",
                mode="lines+markers",
                line=dict(color=CLINICAL_TEAL, width=2.5),
                marker=dict(size=5.5, color=CLINICAL_TEAL),
            )
        )
    return _apply_layout(fig, title, height=345, y_title="Daily Units")


def chart_bar_simple(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    color: str | None = None,
    height: int = 300,
) -> go.Figure:
    if df.empty:
        return _apply_layout(go.Figure(), title, height=height)
    if color:
        fig = px.bar(df, x=x, y=y, color=color, color_discrete_sequence=CHART_SEQUENCE, barmode="stack")
    else:
        fig = px.bar(df, x=x, y=y, color_discrete_sequence=[CLINICAL_TEAL])
    return _apply_layout(fig, title, height=height, y_title="Units")


def chart_line_simple(df: pd.DataFrame, x: str, y: str, title: str, y_title: str = "Units", height: int = 300) -> go.Figure:
    if df.empty:
        return _apply_layout(go.Figure(), title, height=height)
    fig = go.Figure(
        go.Scatter(
            x=df[x],
            y=df[y],
            mode="lines+markers",
            line=dict(color=CLINICAL_TEAL, width=2.4),
            marker=dict(size=5.5),
        )
    )
    return _apply_layout(fig, title, height=height, y_title=y_title)
