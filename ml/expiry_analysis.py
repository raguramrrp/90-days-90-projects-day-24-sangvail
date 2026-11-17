"""Component and blood-group expiry exposure & wastage trend analytics."""

from __future__ import annotations

from datetime import date
from typing import Optional
import pandas as pd
from sqlalchemy.orm import Session

from backend.services.expiry_service import get_expiry_monitor_df, get_wastage_history_df


def summarize_expiry_exposure(
    session: Session,
    blood_bank_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> dict:
    """Compute expiry bucket summaries and historical wastage breakdowns."""
    today = as_of or date.today()
    exp_df = get_expiry_monitor_df(session, blood_bank_id=blood_bank_id, as_of=today)
    wast_df = get_wastage_history_df(session, blood_bank_id=blood_bank_id)

    active = exp_df[exp_df["inventory_status"].isin(["Released", "Reserved"])] if not exp_df.empty else pd.DataFrame()

    expired_count = int((exp_df["expiry_category"] == "Expired").sum()) if not exp_df.empty else 0
    within_warning = (
        int(active["expiry_category"].isin(["Critical Window", "Approaching Expiry"]).sum())
        if not active.empty
        else 0
    )
    within_7 = int(((active["remaining_days"] >= 0) & (active["remaining_days"] <= 7)).sum()) if not active.empty else 0
    within_30 = int(((active["remaining_days"] >= 0) & (active["remaining_days"] <= 30)).sum()) if not active.empty else 0

    by_comp = (
        active.groupby(["component", "expiry_category"], as_index=False)["id"].count().rename(columns={"id": "units"})
        if not active.empty
        else pd.DataFrame(columns=["component", "expiry_category", "units"])
    )
    by_group = (
        active.groupby(["blood_group", "expiry_category"], as_index=False)["id"].count().rename(columns={"id": "units"})
        if not active.empty
        else pd.DataFrame(columns=["blood_group", "expiry_category", "units"])
    )
    monthly_wastage = (
        wast_df.groupby(["event_month", "event_type"], as_index=False)["transaction_id"]
        .count()
        .rename(columns={"transaction_id": "units"})
        .sort_values("event_month")
        if not wast_df.empty
        else pd.DataFrame(columns=["event_month", "event_type", "units"])
    )
    discard_reasons = (
        wast_df.groupby("reason", as_index=False)["transaction_id"]
        .count()
        .rename(columns={"transaction_id": "units"})
        .sort_values("units", ascending=False)
        if not wast_df.empty
        else pd.DataFrame(columns=["reason", "units"])
    )

    return {
        "expired_units": expired_count,
        "within_warning_window": within_warning,
        "expiring_within_7_days": within_7,
        "expiring_within_30_days": within_30,
        "expiry_df": exp_df,
        "wastage_df": wast_df,
        "by_component_df": by_comp,
        "by_group_df": by_group,
        "monthly_wastage_df": monthly_wastage,
        "discard_reasons_df": discard_reasons,
    }
