"""Two-tier architectural horizontal navigation, editorial split login gate, and native st.html rendering."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional
import streamlit as st
from sqlalchemy.orm import Session

from app.config import (
    APP_FULL_NAME,
    APP_NAME,
    APP_TAGLINE,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_PATIENT_PASSWORD,
    DEFAULT_PATIENT_USERNAME,
    SYNTHETIC_DATA_DISCLAIMER,
)
from backend.auth import authenticate_user, register_patient_user
from backend.database import get_database_status
from backend.repositories.master_repo import get_blood_banks
from backend.services.analytics_service import get_needs_attention_alerts

PRIMARY_NAV_ITEMS = [
    ("Overview", "Overview"),
    ("Inventory", "Inventory"),
    ("Donations", "Donations"),
    ("Requests", "Requests"),
    ("Network", "Network"),
    ("Expiry", "Expiry"),
    ("Intelligence", "Intelligence"),
    ("Reports", "Reports"),
]

SUB_NAV_MAP = {
    "Inventory": [("Inventory", "Unit Inventory"), ("Screening", "Screening & Release")],
    "Screening": [("Inventory", "Unit Inventory"), ("Screening", "Screening & Release")],
    "Donations": [("Donations", "Donation Register"), ("Screening", "Screening & Release")],
    "Intelligence": [
        ("Intelligence", "Demand Intelligence"),
        ("Forecasting", "Forecasting & Shortage"),
        ("Data Quality", "Data Quality Centre"),
    ],
    "Forecasting": [
        ("Intelligence", "Demand Intelligence"),
        ("Forecasting", "Forecasting & Shortage"),
        ("Data Quality", "Data Quality Centre"),
    ],
    "Data Quality": [
        ("Intelligence", "Demand Intelligence"),
        ("Forecasting", "Forecasting & Shortage"),
        ("Data Quality", "Data Quality Centre"),
    ],
}

BREADCRUMB_MAP = {
    "Overview": "SANGVAIL / OPERATIONS / OVERVIEW",
    "Inventory": "SANGVAIL / OPERATIONS / UNIT INVENTORY",
    "Donations": "SANGVAIL / OPERATIONS / DONATION REGISTER",
    "Screening": "SANGVAIL / OPERATIONS / SCREENING & RELEASE",
    "Requests": "SANGVAIL / OPERATIONS / BLOOD REQUESTS & FEFO",
    "Expiry": "SANGVAIL / OPERATIONS / EXPIRY MONITOR",
    "Intelligence": "SANGVAIL / INTELLIGENCE / DEMAND INTELLIGENCE",
    "Forecasting": "SANGVAIL / INTELLIGENCE / FORECASTING & SHORTAGE",
    "Data Quality": "SANGVAIL / GOVERNANCE / DATA QUALITY CENTRE",
    "Reports": "SANGVAIL / REPORTING / REPORTS & EXPORTS",
    "Settings": "SANGVAIL / ADMINISTRATION / SETTINGS",
}

from urllib.parse import quote as _url_quote


def _svg_img(svg_markup: str, width: int, height: int, alt: str = "") -> str:
    """Embed crisp vector icons via data-URI <img> so Streamlit's HTML sanitizer never strips <svg>."""
    encoded = _url_quote(svg_markup, safe="")
    return f'<img src="data:image/svg+xml;utf8,{encoded}" width="{width}" height="{height}" alt="{alt}" style="display:block; flex-shrink:0;" />'


LOGO_SVG_DARK = _svg_img(
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">'
    '<rect x="1.5" y="1.5" width="21" height="21" rx="5" fill="#0F766E"/>'
    '<path d="M12 5.4L16.3 12C17 13.1 16.8 14.8 15.8 15.8C14.7 16.9 13.4 17.4 12 17.4C10.6 17.4 9.3 16.9 8.2 15.8C7.2 14.8 7 13.1 7.7 12L12 5.4Z" stroke="#FFFFFF" stroke-width="1.6" fill="none"/>'
    '<line x1="12" y1="11.2" x2="12" y2="15" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round"/>'
    '<line x1="10.1" y1="13.1" x2="13.9" y2="13.1" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round"/>'
    '</svg>',
    24, 24, "SANGVAIL",
)

LOGO_SVG_SHIELD = _svg_img(
    '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">'
    '<path d="M16 2.5L27 6.8V15.4C27 22.1 22.3 27.6 16 29.5C9.7 27.6 5 22.1 5 15.4V6.8L16 2.5Z" fill="#14585A" stroke="#99F6E4" stroke-width="1.6"/>'
    '<path d="M16 8.5C16 8.5 11.4 13.7 11.4 17C11.4 19.5 13.5 21.6 16 21.6C18.5 21.6 20.6 19.5 20.6 17C20.6 13.7 16 8.5 16 8.5Z" fill="rgba(255,255,255,0.14)" stroke="#FFFFFF" stroke-width="1.5"/>'
    '<line x1="16" y1="14.6" x2="16" y2="19.2" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round"/>'
    '<line x1="13.7" y1="16.9" x2="18.3" y2="16.9" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round"/>'
    '</svg>',
    32, 32, "SANGVAIL",
)

LOGIN_BG_PATTERN_SVG = ""

ICON_COLDCHAIN = _svg_img(
    '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#99F6E4" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z"/></svg>',
    15, 15,
)
ICON_PULSE = _svg_img(
    '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#99F6E4" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
    '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    15, 15,
)
ICON_SHIELD = _svg_img(
    '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#99F6E4" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>',
    15, 15,
)
ICON_LOCK_SMALL = _svg_img(
    '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#64748B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    13, 13,
)


def render_html(html: str) -> None:
    """Render raw HTML natively via st.html so Markdown never corrupts tags or SVGs."""
    st.html(html)


def inject_theme_css() -> None:
    css_path = Path(__file__).resolve().parent.parent / "styles" / "theme.css"
    if css_path.exists():
        st.html(f"<style>{css_path.read_text(encoding='utf-8')}</style>")


def init_session_state() -> None:
    defaults = {
        "authenticated": False,
        "current_user": None,
        "active_page": "Overview",
        "patient_active_tab": "Availability",
        "selected_bank_id": None,
        "shared_blood_groups": [],
        "shared_components": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def navigate_to(page_key: str, blood_group: str | None = None, component: str | None = None) -> None:
    st.session_state["active_page"] = page_key
    if blood_group:
        st.session_state["shared_blood_groups"] = [blood_group]
    if component:
        st.session_state["shared_components"] = [component]
    st.rerun()


def render_login_screen(session: Session) -> None:
    """Render full-viewport edge-to-edge split authentication screen."""
    render_html(
        """
        <style>
        .stApp:has(.sv-login-left),
        .stApp:has(.sv-login-left) .stAppViewContainer,
        .stApp:has(.sv-login-left) section[data-testid="stMain"] {
            background-color: #FFFFFF !important;
            overflow-x: hidden !important;
        }
        .stApp:has(.sv-login-left) .block-container,
        .stApp:has(.sv-login-left) div[data-testid="stAppViewBlockContainer"] {
            padding: 0 !important;
            margin: 0 !important;
            max-width: 100% !important;
            width: 100% !important;
            min-height: 100vh !important;
        }
        .stApp:has(.sv-login-left) .block-container > div > div[data-testid="stVerticalBlock"] {
            gap: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.sv-login-left) {
            gap: 0 !important;
            min-height: 100vh !important;
            align-items: stretch !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.sv-login-left) > div[data-testid="stColumn"]:first-child {
            padding: 0 !important;
            background-color: #0D2F33 !important;
            min-height: 100vh !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.sv-login-left) > div[data-testid="stColumn"]:first-child > div[data-testid="stVerticalBlock"] {
            gap: 0 !important;
            min-height: 100vh !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.sv-login-left) > div[data-testid="stColumn"]:last-child {
            background-color: #FFFFFF !important;
            min-height: 100vh !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: flex-start !important;
            align-items: center !important;
            padding: 16vh 4rem 3rem 4rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.sv-login-left) > div[data-testid="stColumn"]:last-child > div {
            width: 100% !important;
            max-width: 420px !important;
            margin: 0 auto !important;
        }
        .stApp:has(.sv-login-left) .stTextInput input {
            height: 42px !important;
            min-height: 42px !important;
            border-radius: 6px !important;
            border: 1px solid #CBD5E1 !important;
            background-color: #FFFFFF !important;
            color: #0F172A !important;
            font-size: 13.5px !important;
        }
        .stApp:has(.sv-login-left) .stButton > button,
        .stApp:has(.sv-login-left) .stFormSubmitButton > button {
            height: 42px !important;
            min-height: 42px !important;
            border-radius: 6px !important;
            font-size: 13.5px !important;
            box-shadow: none !important;
        }
        </style>
        """
    )

    left_col, right_col = st.columns([0.44, 0.56], gap="small")

    with left_col:
        render_html(
            f"""
            <div class="sv-login-left">
                <div class="sv-login-brand">
                    {LOGO_SVG_SHIELD}
                    <span class="sv-login-hero-title">{APP_NAME}</span>
                </div>
                <div class="sv-login-mid">
                    <h1 class="sv-login-headline">Blood Bank Operations &amp; Inventory Control</h1>
                    <div class="sv-login-rule"></div>
                    <p class="sv-login-subheadline">
                        Unit-level custody, mandatory screening verification, cold-chain dispatch,
                        and regional blood demand planning.
                    </p>
                </div>
                <div class="sv-login-meta">
                    <div class="sv-login-meta-item">
                        <span class="sv-login-meta-val">4 Hubs</span>
                        <span class="sv-login-meta-lbl">Regional Network</span>
                    </div>
                    <div class="sv-login-meta-item">
                        <span class="sv-login-meta-val">8 Groups</span>
                        <span class="sv-login-meta-lbl">ABO / Rh Live Stock</span>
                    </div>
                    <div class="sv-login-meta-item">
                        <span class="sv-login-meta-val">FEFO</span>
                        <span class="sv-login-meta-lbl">Expiry-First Allocation</span>
                    </div>
                </div>
            </div>
            """
        )

    with right_col:
        tab_admin, tab_patient, tab_register = st.tabs(
            ["Administrator", "Patient / User", "Create Account"]
        )

        with tab_admin:
            render_html(
                """
                <div class="sv-auth-card-header">
                    <div class="sv-auth-title">Administrator Sign In</div>
                    <div class="sv-auth-subtitle">Sign in to manage inventory, screening, requests, and dispatch.</div>
                </div>
                """
            )
            with st.form("sangvail_login_form", clear_on_submit=False, border=False):
                username = st.text_input("Username", value=DEFAULT_ADMIN_USERNAME)
                password = st.text_input("Password", value="", type="password", placeholder="Enter password")
                render_html('<div style="height:4px;"></div>')
                submit = st.form_submit_button("Sign In", type="primary", width="stretch")

            quick_access = st.button("Quick Admin Sign In", type="secondary", width="stretch", key="btn_quick_admin_login")

            if submit or quick_access:
                with st.spinner("Signing in..."):
                    u_in = DEFAULT_ADMIN_USERNAME if quick_access else username
                    p_in = DEFAULT_ADMIN_PASSWORD if quick_access else password
                    user = authenticate_user(session, u_in, p_in)
                    if user and user.role == "Administrator":
                        st.session_state["authenticated"] = True
                        st.session_state["current_user"] = {
                            "id": user.id,
                            "username": user.username,
                            "display_name": user.display_name,
                            "role": user.role,
                        }
                        st.session_state["active_page"] = "Overview"
                        st.rerun()
                    else:
                        st.error("Invalid administrator credentials.")

        with tab_patient:
            render_html(
                """
                <div class="sv-auth-card-header">
                    <div class="sv-auth-title">Patient / User Sign In</div>
                    <div class="sv-auth-subtitle">View live availability, submit blood requests, book surgery holds, and track dispatch.</div>
                </div>
                """
            )
            with st.form("sangvail_patient_login_form", clear_on_submit=False, border=False):
                p_user = st.text_input("Username", value=DEFAULT_PATIENT_USERNAME, key="pt_login_user")
                p_pass = st.text_input("Password", value="", type="password", placeholder="Enter password", key="pt_login_pass")
                render_html('<div style="height:4px;"></div>')
                p_submit = st.form_submit_button("Sign In", type="primary", width="stretch")

            p_quick = st.button("Quick Patient Sign In", type="secondary", width="stretch", key="btn_quick_patient_login")

            if p_submit or p_quick:
                with st.spinner("Signing in..."):
                    u_in = DEFAULT_PATIENT_USERNAME if p_quick else p_user
                    pw_in = DEFAULT_PATIENT_PASSWORD if p_quick else p_pass
                    user = authenticate_user(session, u_in, pw_in)
                    if user:
                        st.session_state["authenticated"] = True
                        st.session_state["current_user"] = {
                            "id": user.id,
                            "username": user.username,
                            "display_name": user.display_name,
                            "role": user.role,
                        }
                        st.session_state["patient_active_tab"] = "Availability"
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")

        with tab_register:
            render_html(
                """
                <div class="sv-auth-card-header">
                    <div class="sv-auth-title">Create Account</div>
                    <div class="sv-auth-subtitle">Register a patient or requester account for live blood stock access.</div>
                </div>
                """
            )
            with st.form("sangvail_register_form", clear_on_submit=False, border=False):
                reg_name = st.text_input("Full Name *", placeholder="Full name")
                reg_user = st.text_input("Username *", placeholder="Choose a username")
                reg_pass = st.text_input("Password *", type="password", placeholder="Minimum 6 characters")
                reg_pass2 = st.text_input("Confirm Password *", type="password", placeholder="Re-enter password")
                render_html('<div style="height:4px;"></div>')
                reg_submit = st.form_submit_button("Create Account", type="primary", width="stretch")

            if reg_submit:
                if reg_pass != reg_pass2:
                    st.error("Passwords do not match.")
                else:
                    try:
                        new_u = register_patient_user(session, reg_user, reg_pass, reg_name)
                        session.commit()
                        st.session_state["authenticated"] = True
                        st.session_state["current_user"] = {
                            "id": new_u.id,
                            "username": new_u.username,
                            "display_name": new_u.display_name,
                            "role": new_u.role,
                        }
                        st.session_state["patient_active_tab"] = "Availability"
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        st.error(str(exc))

        render_html('<div class="sv-auth-note">Sangvail Blood Services</div>')


def render_top_navigation(session: Session) -> Optional[int]:
    """Render clean two-tier horizontal masthead with zero button wrapping or label truncation."""
    banks = get_blood_banks(session)
    bank_options = {"All Blood Banks": None}
    for b in banks:
        bank_options[b.bank_name] = b.id

    active_page = st.session_state["active_page"]
    active_parent = (
        "Inventory" if active_page == "Screening"
        else "Intelligence" if active_page in ("Forecasting", "Data Quality")
        else active_page
    )

    with st.container(border=True):
        brand_col, bank_col, alert_col, settings_col, user_col = st.columns(
            [4.2, 2.2, 1.35, 1.05, 1.1], vertical_alignment="center"
        )

        with brand_col:
            render_html(
                f"""
                <div class="sv-brand-wrap">
                    {LOGO_SVG_DARK}
                    <span class="sv-wordmark">{APP_NAME}</span>
                </div>
                """
            )

        with bank_col:
            labels = list(bank_options.keys())
            current_id = st.session_state.get("selected_bank_id")
            curr_idx = 0
            for idx, lbl in enumerate(labels):
                if bank_options[lbl] == current_id:
                    curr_idx = idx
                    break
            chosen_lbl = st.selectbox(
                "Blood Bank",
                options=labels,
                index=curr_idx,
                key="topbar_bank_select",
                label_visibility="collapsed",
            )
            st.session_state["selected_bank_id"] = bank_options[chosen_lbl]

        selected_bank_id = st.session_state["selected_bank_id"]
        alerts = get_needs_attention_alerts(session, blood_bank_id=selected_bank_id)
        crit_count = sum(1 for a in alerts if a["severity"] == "Critical")

        with alert_col:
            alert_label = f"Alerts · {len(alerts)}" if alerts else "Alerts · 0"
            with st.popover(alert_label, width="stretch"):
                st.markdown(f"**Operational Alerts** ({crit_count} critical)")
                if not alerts:
                    st.caption("No active operational alerts.")
                else:
                    for i, a in enumerate(alerts[:6]):
                        badge_cls = "critical" if a["severity"] == "Critical" else "warning"
                        render_html(
                            f'<div style="margin-bottom:4px;">'
                            f'<span class="sv-badge {badge_cls}">{a["severity"]}</span>'
                            f'<strong style="font-size:12px; color:#202A28;">{a["title"]}</strong><br/>'
                            f'<span style="font-size:11px; color:#75807C;">{a["detail"]}</span>'
                            f'</div>'
                        )
                        if st.button(f"Open {a['target_page']}", key=f"pop_alert_{i}", width="stretch"):
                            navigate_to(
                                a["target_page"],
                                blood_group=a.get("filter_blood_group"),
                                component=a.get("filter_component"),
                            )

        with settings_col:
            if st.button(
                "Settings",
                key="nav_Settings",
                type="primary" if active_page == "Settings" else "secondary",
                width="stretch",
            ):
                st.session_state["active_page"] = "Settings"
                st.rerun()

        with user_col:
            user = st.session_state.get("current_user") or {
                "username": "admin",
                "display_name": "Operations Administrator",
                "role": "Administrator",
            }
            with st.popover(user["username"], width="stretch"):
                st.markdown(f"**{user['display_name']}**")
                st.caption(f"Role: {user['role']}")
                if st.button("Sign Out", key="btn_sign_out", width="stretch"):
                    st.session_state["authenticated"] = False
                    st.session_state["current_user"] = None
                    st.rerun()

        render_html('<div style="height:1px; background:#E2E8F0; margin: 10px 0 12px 0;"></div>')

        nav_cols = st.columns(len(PRIMARY_NAV_ITEMS), gap="small")
        for col, (key, label) in zip(nav_cols, PRIMARY_NAV_ITEMS):
            with col:
                is_active = active_parent == key
                if st.button(
                    label,
                    key=f"nav_{key}",
                    type="primary" if is_active else "secondary",
                    width="stretch",
                ):
                    st.session_state["active_page"] = key
                    st.rerun()

    if active_page in SUB_NAV_MAP:
        sub_items = SUB_NAV_MAP[active_page]
        s_cols = st.columns([1.6] * len(sub_items) + [5.2])
        for col, (s_key, s_label) in zip(s_cols[: len(sub_items)], sub_items):
            with col:
                if st.button(
                    s_label,
                    key=f"subnav_{s_key}",
                    type="primary" if active_page == s_key else "secondary",
                    width="stretch",
                ):
                    st.session_state["active_page"] = s_key
                    st.rerun()

    return st.session_state["selected_bank_id"]


def render_patient_navigation(user: dict) -> str:
    """Render clean, spacious horizontal top navigation exclusively for Patient / User Portal accounts."""
    patient_tabs = [
        ("Availability", "Live Availability"),
        ("New Request", "Submit Request"),
        ("Surgery Booking", "Surgery Booking"),
        ("My Requests", "My Requests & Dispatch"),
        ("Payments", "Fees & Receipts"),
    ]
    active_tab = st.session_state.get("patient_active_tab", "Availability")

    with st.container(border=True):
        brand_col, spacer_col, role_col, user_col = st.columns([4.2, 2.8, 1.6, 1.3], vertical_alignment="center")
        with brand_col:
            render_html(
                f"""
                <div class="sv-brand-wrap">
                    {LOGO_SVG_DARK}
                    <span class="sv-wordmark">{APP_NAME}</span>
                </div>
                """
            )
        with role_col:
            render_html('<div style="text-align:right;"><span class="sv-badge normal">Patient Portal</span></div>')
        with user_col:
            with st.popover(user["username"], width="stretch"):
                st.markdown(f"**{user['display_name']}**")
                st.caption("Account Type: Patient / User")
                if st.button("Sign Out", key="btn_pt_sign_out", width="stretch"):
                    st.session_state["authenticated"] = False
                    st.session_state["current_user"] = None
                    st.rerun()

        render_html('<div style="height:1px; background:#E2E8F0; margin: 10px 0 12px 0;"></div>')

        t_cols = st.columns(len(patient_tabs), gap="small")
        for col, (t_key, t_label) in zip(t_cols, patient_tabs):
            with col:
                if st.button(
                    t_label,
                    key=f"pt_nav_{t_key}",
                    type="primary" if active_tab == t_key else "secondary",
                    width="stretch",
                ):
                    st.session_state["patient_active_tab"] = t_key
                    st.rerun()

    return st.session_state.get("patient_active_tab", "Availability")


def render_page_header(page_key: str, title: str, description: str = "") -> None:
    """Render clean editorial workstation header with title and date stamp."""
    today_label = date.today().strftime("%Y-%m-%d")
    render_html(
        f"""
        <div class="sv-header-block">
            <h1 class="sv-page-title">{title}</h1>
            <div class="sv-header-stamp">AS OF {today_label}</div>
        </div>
        """
    )


def render_footer_disclaimer() -> None:
    render_html(f'<div class="sv-disclaimer">{SYNTHETIC_DATA_DISCLAIMER}</div>')
