"""Flat clinical KPI summary cards, section headers, and clean operational tables."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.navigation import render_html


def render_kpi_strip(items: list[dict]) -> None:
    """
    Render flat institutional KPI summary cards grid via native st.html.

    Each item: {"label": str, "value": str|int, "meta": str, "tone": ""|"accent"|"warning"|"critical"}
    """
    cards = []
    for item in items:
        tone = item.get("tone", "")
        card_tone = f"tone-{tone}" if tone in ("warning", "critical") else ""
        meta = item.get("meta", "")
        cards.append(
            f'<div class="sv-kpi-card {card_tone}">'
            f'<div class="sv-kpi-label">{item["label"]}</div>'
            f'<div class="sv-kpi-value {tone}">{item["value"]}</div>'
            f'<div class="sv-kpi-meta">{meta}</div>'
            f'</div>'
        )
    grid_cls = "sv-kpi-grid cols-3" if len(items) == 6 else "sv-kpi-grid"
    render_html(f'<div class="{grid_cls}">{"".join(cards)}</div>')


def render_section_title(title: str) -> None:
    render_html(f'<div class="sv-section-title">{title}</div>')


def render_empty_state(message: str) -> None:
    render_html(f'<div class="sv-empty-state">{message}</div>')


def render_clean_table(df: pd.DataFrame, hide_columns: list[str] | None = None, height: int | None = None) -> None:
    """Display a clean operational DataFrame with tabular alignment and formatted column headers."""
    if df.empty:
        render_empty_state("No operational records match the current filters.")
        return
    display = df.copy()
    if hide_columns:
        display = display.drop(columns=[c for c in hide_columns if c in display.columns])
    display.columns = [str(c).replace("_", " ").title() for c in display.columns]
    kwargs = {"width": "stretch", "hide_index": True}
    if height:
        kwargs["height"] = height
    st.dataframe(display, **kwargs)
