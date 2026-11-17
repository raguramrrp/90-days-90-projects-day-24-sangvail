"""Module 13 — Blood Bank Configuration, Thresholds, Component Policies & System Settings."""

from __future__ import annotations

from typing import Optional
import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.components.forms import render_validation_error
from app.components.navigation import render_page_header
from app.components.tables import render_clean_table, render_kpi_strip, render_section_title
from backend.database import get_database_status
from backend.models import AuditLog
from backend.repositories.master_repo import get_blood_banks, get_blood_groups, get_components
from backend.schemas import ThresholdUpdate
from backend.services.settings_service import (
    get_setting,
    get_storage_locations,
    list_thresholds_df,
    save_storage_locations,
    set_setting,
    update_blood_bank_profile,
    update_component_policy,
    upsert_stock_threshold,
)


def render_settings_page(session: Session, blood_bank_id: Optional[int], actor: str) -> None:
    render_page_header(
        "Settings",
        "Configuration & Operational Policies",
        "Manage blood bank profiles, component-specific shelf-life rules, configurable stock thresholds, storage locations, and system diagnostics.",
    )

    db_status = get_database_status()
    render_kpi_strip(
        [
            {"label": "Database Engine", "value": db_status["dialect"].upper(), "meta": f"Driver: {db_status['driver']}", "tone": "accent" if db_status["connected"] else "critical"},
            {"label": "Connection Health", "value": "Connected" if db_status["connected"] else "Disconnected", "meta": db_status["target"][:48], "tone": "accent" if db_status["connected"] else "critical"},
            {"label": "Screening SLA", "value": f"{get_setting(session, 'screening_sla_days', '2')} days", "meta": "Alert cutoff for pending units", "tone": ""},
            {"label": "Compatibility Policy", "value": "Exact-Label Policy", "meta": "Requires human approval", "tone": "warning"},
        ]
    )

    tab_thresholds, tab_components, tab_bank, tab_app, tab_audit = st.tabs(
        ["Stock Thresholds & Expiry Windows", "Component Policies", "Blood Bank & Storage", "Application Preferences", "Audit Log"]
    )

    banks = get_blood_banks(session)
    groups = get_blood_groups(session)
    comps = get_components(session)

    with tab_thresholds:
        render_section_title("Configure Minimum Stock & Expiry Warning Windows")
        st.caption("Shortage alerts and expiry windows are read dynamically from this table — no hardcoded thresholds.")

        c_form, c_tbl = st.columns([1.2, 2.0])
        with c_form:
            bank_map = {b.bank_name: b.id for b in banks}
            bg_map = {g.display_name: g.id for g in groups}
            comp_map = {c.component_name: c.id for c in comps}
            with st.form("threshold_upsert_form"):
                sel_bank = st.selectbox("Blood Bank", options=list(bank_map.keys()))
                sel_bg = st.selectbox("Blood Group", options=list(bg_map.keys()))
                sel_comp = st.selectbox("Blood Component", options=list(comp_map.keys()))
                min_stock = st.number_input("Minimum Stock Floor (Units)", min_value=0, max_value=200, value=6)
                warn_days = st.number_input("Expiry Warning Window (Days)", min_value=1, max_value=180, value=7)
                crit_days = st.number_input("Expiry Critical Window (Days)", min_value=1, max_value=90, value=3)
                if st.form_submit_button("Save Threshold Policy", type="primary", width="stretch"):
                    try:
                        payload = ThresholdUpdate(
                            blood_bank_id=bank_map[sel_bank],
                            blood_group_id=bg_map[sel_bg],
                            component_id=comp_map[sel_comp],
                            minimum_stock=int(min_stock),
                            warning_days=int(warn_days),
                            critical_days=int(crit_days),
                        )
                        upsert_stock_threshold(session, payload, actor=actor)
                        session.commit()
                        st.success(f"Updated threshold for {sel_bg} {sel_comp}.")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

        with c_tbl:
            th_df = list_thresholds_df(session, blood_bank_id=blood_bank_id)
            render_clean_table(th_df, hide_columns=["id", "blood_bank_id", "blood_group_id", "component_id"], height=390)

    with tab_components:
        render_section_title("Component-Specific Storage & Shelf-Life Policies")
        comp_df = pd.DataFrame(
            [
                {
                    "component_name": c.component_name,
                    "short_code": c.short_code,
                    "default_shelf_life_days": c.default_shelf_life_days,
                    "storage_temp_range": c.storage_temp_range,
                    "enabled": c.enabled,
                }
                for c in comps
            ]
        )
        render_clean_table(comp_df, height=220)

        comp_obj_map = {c.component_name: c for c in comps}
        sel_c_name = st.selectbox("Select Component to Edit", options=list(comp_obj_map.keys()), key="edit_comp_sel")
        c_obj = comp_obj_map[sel_c_name]
        with st.form("edit_comp_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                shelf_val = st.number_input("Default Shelf Life (Days)", min_value=1, max_value=730, value=int(c_obj.default_shelf_life_days))
            with c2:
                temp_val = st.text_input("Storage Temperature Policy", value=c_obj.storage_temp_range)
            with c3:
                en_val = st.checkbox("Component Enabled", value=bool(c_obj.enabled))
            if st.form_submit_button("Update Component Policy", type="primary"):
                try:
                    update_component_policy(session, c_obj.id, int(shelf_val), temp_val, en_val, actor=actor)
                    session.commit()
                    st.success(f"Updated policy for {c_obj.component_name}.")
                    st.rerun()
                except Exception as exc:
                    session.rollback()
                    render_validation_error(exc)

    with tab_bank:
        col_b, col_s = st.columns(2)
        with col_b:
            render_section_title("Blood Bank Profile")
            bank_obj_map = {b.bank_name: b for b in banks}
            sel_b_name = st.selectbox("Select Blood Bank", options=list(bank_obj_map.keys()), key="edit_bank_sel")
            b_obj = bank_obj_map[sel_b_name]
            with st.form("edit_bank_form"):
                bn = st.text_input("Blood Bank Name", value=b_obj.bank_name)
                addr = st.text_input("Location / Address", value=b_obj.address)
                cont = st.text_input("Operational Contact", value=b_obj.contact)
                tz = st.selectbox("Reporting Timezone", options=["UTC", "Asia/Kolkata", "America/New_York", "Europe/London"], index=0)
                if st.form_submit_button("Save Blood Bank Profile", type="primary"):
                    try:
                        update_blood_bank_profile(session, b_obj.id, bn, addr, cont, tz, actor=actor)
                        session.commit()
                        st.success("Blood bank profile updated.")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        render_validation_error(exc)

        with col_s:
            render_section_title("Configured Storage Location Labels")
            current_locs = get_storage_locations(session)
            with st.form("storage_locs_form"):
                locs_text = st.text_area("One storage location per line", value="\n".join(current_locs), height=210)
                if st.form_submit_button("Save Storage Locations", type="primary"):
                    new_list = [line.strip() for line in locs_text.splitlines() if line.strip()]
                    if not new_list:
                        st.error("At least one storage location is required.")
                    else:
                        save_storage_locations(session, new_list, actor=actor)
                        session.commit()
                        st.success(f"Saved {len(new_list)} storage location labels.")
                        st.rerun()

    with tab_app:
        render_section_title("Application & Notification Preferences")
        with st.form("app_prefs_form"):
            c1, c2 = st.columns(2)
            with c1:
                date_fmt = st.selectbox("Date Format", ["YYYY-MM-DD", "DD-MMM-YYYY", "MM/DD/YYYY"], index=0)
                num_fmt = st.selectbox("Number Format", ["1,234", "1234"], index=0)
            with c2:
                sla_days = st.number_input(
                    "Screening Pending Alert SLA (Days)",
                    min_value=1,
                    max_value=14,
                    value=int(get_setting(session, "screening_sla_days", "2") or 2),
                )
                def_range = st.selectbox("Default Analytics Range (Days)", ["30", "90", "180", "365"], index=1)
            if st.form_submit_button("Save Application Settings", type="primary"):
                set_setting(session, "date_format", date_fmt, actor=actor)
                set_setting(session, "number_format", num_fmt, actor=actor)
                set_setting(session, "screening_sla_days", str(int(sla_days)), actor=actor)
                set_setting(session, "default_date_range_days", def_range, actor=actor)
                session.commit()
                st.success("Application preferences saved.")
                st.rerun()

    with tab_audit:
        render_section_title("Recent Administrative Audit Log")
        audits = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)).all()
        audit_df = pd.DataFrame(
            [
                {
                    "timestamp": a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "actor": a.actor_name,
                    "action": a.action,
                    "entity_type": a.entity_type,
                    "entity_id": a.entity_id,
                    "details": a.details,
                }
                for a in audits
            ]
        )
        render_clean_table(audit_df, height=380)
