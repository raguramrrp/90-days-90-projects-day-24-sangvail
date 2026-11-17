"""Compact validated operational form helpers."""

from __future__ import annotations

import streamlit as st


def render_validation_error(exc: Exception) -> None:
    """Display clean, actionable validation or domain rule feedback."""
    st.error(f"Action blocked by validation guardrail: {exc}")
