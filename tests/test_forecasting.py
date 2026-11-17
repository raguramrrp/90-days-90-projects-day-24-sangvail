"""Automated tests for Modules 9 & 10 — Demand Forecasting & Shortage Planning."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.demand_forecasting import forecast_series
from ml.model_evaluation import evaluate_models_chronologically
from ml.shortage_analysis import compute_shortage_planning_df


def _build_synthetic_daily_series(days: int = 120, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=days, freq="D")
    base = 4.0 + 1.2 * np.sin(2 * np.pi * np.arange(days) / 7.0) + rng.normal(0, 0.5, days)
    return pd.Series(np.clip(base, 0.0, None), index=idx)


def test_forecast_is_reproducible_and_non_negative():
    series = _build_synthetic_daily_series(120, seed=42)
    r1 = forecast_series(series, horizon_days=14, model_choice="Random Forest Regressor", random_state=42)
    r2 = forecast_series(series, horizon_days=14, model_choice="Random Forest Regressor", random_state=42)

    assert len(r1["forecast_df"]) == 14
    assert (r1["forecast_df"]["predicted_demand"] >= 0).all()
    assert (r1["forecast_df"]["lower_bound"] >= 0).all()
    assert (r1["forecast_df"]["upper_bound"] >= r1["forecast_df"]["predicted_demand"]).all()
    pd.testing.assert_frame_equal(r1["forecast_df"], r2["forecast_df"])


def test_chronological_evaluation_and_baselines():
    series = _build_synthetic_daily_series(120, seed=99)
    ev = evaluate_models_chronologically(series, test_days=21, random_state=42)
    assert ev["sufficient_data"] is True
    model_names = {m["model_name"] for m in ev["metrics"]}
    assert "Seasonal Naive (Lag-7)" in model_names
    assert "Moving Average (7d)" in model_names
    assert "Random Forest Regressor" in model_names
    assert all(m["mae"] >= 0 and m["rmse"] >= 0 for m in ev["metrics"])


def test_sparse_history_falls_back_to_moving_average():
    short_series = _build_synthetic_daily_series(12, seed=7)
    res = forecast_series(short_series, horizon_days=7, model_choice="Auto (Best CV RMSE)")
    assert res["evaluation"]["sufficient_data"] is False
    assert "Moving Average" in res["selected_model"]
    assert "minimum 35 days" in res["limitation_note"]
    assert len(res["forecast_df"]) == 7


def test_empty_series_handled_gracefully():
    res = forecast_series(pd.Series(dtype=float), horizon_days=7)
    assert res["forecast_df"].empty
    assert "No historical" in res["limitation_note"]


def test_shortage_planning_handles_zero_demand_safely(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    sh_df = compute_shortage_planning_df(session, blood_bank_id=bank_id, horizon_days=14)
    assert not sh_df.empty
    # With zero requests in empty test DB, coverage_days must report Unavailable rather than crashing
    assert (sh_df["coverage_days"] == "Unavailable (0 demand)").all()
    assert set(sh_df["planning_status"]).issubset({"Critical", "High", "Moderate", "Stable"})
