"""Shared filter components that preserve operational context across pages."""

from __future__ import annotations

import streamlit as st
from app.config import BLOOD_GROUP_NAMES


def render_blood_group_component_filters(
    component_names: list[str],
    key_prefix: str,
) -> tuple[list[str], list[str]]:
    """Render synchronized blood-group and component multiselect filters."""
    c1, c2 = st.columns(2)
    with c1:
        default_bg = [g for g in st.session_state.get("shared_blood_groups", []) if g in BLOOD_GROUP_NAMES]
        selected_bg = st.multiselect(
            "Blood Group",
            options=BLOOD_GROUP_NAMES,
            default=default_bg,
            key=f"{key_prefix}_bg_filter",
            placeholder="All blood groups",
        )
    with c2:
        default_comp = [c for c in st.session_state.get("shared_components", []) if c in component_names]
        selected_comp = st.multiselect(
            "Blood Component",
            options=component_names,
            default=default_comp,
            key=f"{key_prefix}_comp_filter",
            placeholder="All components",
        )
    st.session_state["shared_blood_groups"] = selected_bg
    st.session_state["shared_components"] = selected_comp
    return selected_bg, selected_comp
