"""Central configuration and domain constants for SANGVAIL."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
SYNTHETIC_DATA_DIR = DATA_DIR / "synthetic"
REPORTS_DIR = BASE_DIR / "reports"
EXPORTS_DIR = BASE_DIR / "exports"
SAVED_MODELS_DIR = BASE_DIR / "ml" / "saved_models"

for _dir in (DATA_DIR, SYNTHETIC_DATA_DIR, REPORTS_DIR, EXPORTS_DIR, SAVED_MODELS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

APP_NAME = os.getenv("APP_NAME", "SANGVAIL")
APP_FULL_NAME = "Blood Bank Inventory, Operations & Demand Intelligence Platform"
APP_TAGLINE = "Better inventory visibility. Smarter resource planning."
APP_VERSION = "1.0.0"
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "UTC")
SYNTHETIC_DATA_SEED = int(os.getenv("SYNTHETIC_DATA_SEED", "42"))

DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
DEFAULT_PATIENT_USERNAME = os.getenv("DEFAULT_PATIENT_USERNAME", "patient")
DEFAULT_PATIENT_PASSWORD = os.getenv("DEFAULT_PATIENT_PASSWORD", "patient123")


def get_database_url() -> str:
    """Resolve DATABASE_URL with an absolute SQLite path fallback."""
    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url:
        if env_url.startswith("sqlite:///") and not env_url.startswith("sqlite:////"):
            rel_part = env_url[len("sqlite:///"):]
            if not Path(rel_part).is_absolute():
                abs_path = (BASE_DIR / rel_part).resolve()
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                return f"sqlite:///{abs_path.as_posix()}"
        return env_url
    default_db = (DATA_DIR / "sangvail.db").resolve()
    return f"sqlite:///{default_db.as_posix()}"


# Design Palette — Clinical Medical SaaS Token System
PALETTE = {
    "bg_main": "#F8FAFC",
    "surface": "#FFFFFF",
    "surface_nested": "#F1F5F9",
    "text_primary": "#0F172A",
    "text_secondary": "#475569",
    "text_muted": "#94A3B8",
    "accent_primary": "#0F766E",
    "accent_secondary": "#0284C7",
    "warning": "#D97706",
    "critical": "#E11D48",
    "slate": "#64748B",
    "border": "#E2E8F0",
    "bg_subtle": "#F0FDFA",
}

# Domain Master Data
BLOOD_GROUPS = [
    ("A", "+", "A+"),
    ("A", "-", "A-"),
    ("B", "+", "B+"),
    ("B", "-", "B-"),
    ("AB", "+", "AB+"),
    ("AB", "-", "AB-"),
    ("O", "+", "O+"),
    ("O", "-", "O-"),
]

BLOOD_GROUP_NAMES = [bg[2] for bg in BLOOD_GROUPS]

# Component-specific configurable storage & shelf-life defaults (demo operational policies)
DEFAULT_COMPONENTS = [
    {
        "component_name": "Red Blood Cells (RBC)",
        "short_code": "RBC",
        "description": "Packed red blood cells stored under controlled refrigeration.",
        "default_shelf_life_days": 42,
        "storage_temp_range": "2°C to 6°C",
        "warning_days": 7,
        "critical_days": 3,
        "enabled": True,
    },
    {
        "component_name": "Platelets",
        "short_code": "PLT",
        "description": "Platelet concentrate stored with continuous agitation.",
        "default_shelf_life_days": 5,
        "storage_temp_range": "20°C to 24°C",
        "warning_days": 2,
        "critical_days": 1,
        "enabled": True,
    },
    {
        "component_name": "Fresh Frozen Plasma (FFP)",
        "short_code": "FFP",
        "description": "Plasma frozen after separation for long-term storage.",
        "default_shelf_life_days": 365,
        "storage_temp_range": "-18°C or colder",
        "warning_days": 30,
        "critical_days": 10,
        "enabled": True,
    },
    {
        "component_name": "Whole Blood",
        "short_code": "WB",
        "description": "Unfractionated collected blood stored under refrigeration.",
        "default_shelf_life_days": 35,
        "storage_temp_range": "2°C to 6°C",
        "warning_days": 7,
        "critical_days": 3,
        "enabled": True,
    },
    {
        "component_name": "Cryoprecipitate",
        "short_code": "CRYO",
        "description": "Frozen clotting factor concentrate prepared from plasma.",
        "default_shelf_life_days": 365,
        "storage_temp_range": "-18°C or colder",
        "warning_days": 30,
        "critical_days": 10,
        "enabled": True,
    },
]

INVENTORY_STATUSES = [
    "Collected",
    "Testing Pending",
    "Quarantined",
    "Released",
    "Reserved",
    "Issued",
    "Expired",
    "Discarded",
    "Rejected",
]

SCREENING_STATUSES = [
    "Pending",
    "In Progress",
    "Cleared",
    "Quarantined",
    "Rejected",
]

DONATION_STATUSES = [
    "Registered",
    "Collected",
    "Processing",
    "Completed",
    "Rejected",
]

REQUEST_URGENCIES = [
    "Routine",
    "Priority",
    "Urgent",
    "Emergency",
]

REQUEST_STATUSES = [
    "Submitted",
    "Under Review",
    "Approved",
    "Partially Allocated",
    "Fully Allocated",
    "Issued",
    "Rejected",
    "Cancelled",
    "Closed",
]

ALLOCATION_STATUSES = [
    "Reserved",
    "Issued",
    "Reversed",
]

DISCARD_REASONS = [
    "Expired while unused",
    "Cold-chain excursion",
    "Container integrity concern",
    "Screening rejection disposal",
    "Processing defect",
    "Administrative recall / quarantine disposal",
]

DEFAULT_STORAGE_LOCATIONS = [
    "Cold Room A — Rack 1 (2-6°C)",
    "Cold Room A — Rack 2 (2-6°C)",
    "Cold Room B — Rack 1 (2-6°C)",
    "Platelet Agitator Unit P1 (20-24°C)",
    "Platelet Agitator Unit P2 (20-24°C)",
    "Ultra-Low Freezer F1 (-30°C)",
    "Ultra-Low Freezer F2 (-30°C)",
    "Quarantine Holding Bay Q1",
]

# Controlled State Machine for Inventory Units
VALID_INVENTORY_TRANSITIONS: dict[str, set[str]] = {
    "Collected": {"Testing Pending", "Quarantined", "Rejected", "Discarded"},
    "Testing Pending": {"Quarantined", "Released", "Rejected", "Expired", "Discarded"},
    "Quarantined": {"Testing Pending", "Released", "Rejected", "Expired", "Discarded"},
    "Released": {"Reserved", "Expired", "Discarded", "Quarantined"},
    "Reserved": {"Issued", "Released", "Expired", "Discarded"},
    "Issued": set(),
    "Expired": {"Discarded"},
    "Discarded": set(),
    "Rejected": {"Discarded"},
}

# Controlled State Machine for Requests
VALID_REQUEST_TRANSITIONS: dict[str, set[str]] = {
    "Submitted": {"Under Review", "Approved", "Rejected", "Cancelled"},
    "Under Review": {"Approved", "Rejected", "Cancelled"},
    "Approved": {"Partially Allocated", "Fully Allocated", "Cancelled", "Rejected"},
    "Partially Allocated": {"Partially Allocated", "Fully Allocated", "Approved", "Issued", "Cancelled"},
    "Fully Allocated": {"Issued", "Partially Allocated", "Approved"},
    "Issued": {"Closed"},
    "Rejected": {"Closed"},
    "Cancelled": {"Closed"},
    "Closed": set(),
}

SYNTHETIC_DATA_DISCLAIMER = (
    "Synthetic operational dataset. For planning and educational use only — "
    "not a certified medical device or clinical transfusion decision tool."
)
