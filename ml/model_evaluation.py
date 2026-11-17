"""Chronological time-series model evaluation (Naive, Moving Average, Random Forest)."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, root_mean_squared_error


def build_time_series_features(series: pd.Series) -> pd.DataFrame:
    """Create strictly causal (lagged/calendar) features from a daily demand series."""
    df = pd.DataFrame({"y": series.astype(float)}, index=pd.DatetimeIndex(series.index))
    df["dow"] = df.index.day_of_week
    df["day_of_month"] = df.index.day
    df["month"] = df.index.month
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["lag_1"] = df["y"].shift(1)
    df["lag_7"] = df["y"].shift(7)
    df["lag_14"] = df["y"].shift(14)
    df["roll_mean_7"] = df["y"].shift(1).rolling(7, min_periods=1).mean()
    df["roll_mean_14"] = df["y"].shift(1).rolling(14, min_periods=1).mean()
    df["roll_std_7"] = df["y"].shift(1).rolling(7, min_periods=2).std().fillna(0.0)
    df["trend_idx"] = np.arange(len(df), dtype=float)
    return df


FEATURE_COLS = [
    "dow",
    "day_of_month",
    "month",
    "is_weekend",
    "lag_1",
    "lag_7",
    "lag_14",
    "roll_mean_7",
    "roll_mean_14",
    "roll_std_7",
    "trend_idx",
]


def evaluate_models_chronologically(
    daily_series: pd.Series,
    test_days: int = 28,
    ma_window: int = 7,
    random_state: int = 42,
) -> dict:
    """
    Evaluate Naive (lag-7 / last-value), Moving Average, and Random Forest using a strict
    chronological holdout split without shuffling.
    """
    series = daily_series.sort_index().astype(float)
    n = len(series)
    if n < 35:
        return {
            "sufficient_data": False,
            "reason": (
                f"Only {n} daily observations available (minimum 35 days required for chronological "
                "train/test evaluation). Falling back to Moving Average baseline."
            ),
            "best_model": "Moving Average (7d)",
            "metrics": [],
            "rf_model": None,
            "residual_std": float(series.std()) if n > 1 else 0.5,
        }

    holdout = min(test_days, max(7, n // 5))
    train = series.iloc[:-holdout]
    test = series.iloc[-holdout:]
    y_true = test.values

    # 1. Seasonal Naive (lag-7 where available, else last value)
    naive_preds = []
    full_vals = series.values
    split_idx = len(train)
    for i in range(holdout):
        idx = split_idx + i
        pred = full_vals[idx - 7] if idx >= 7 else full_vals[idx - 1]
        naive_preds.append(max(0.0, float(pred)))
    naive_arr = np.array(naive_preds)

    # 2. Moving Average (rolling mean of prior ma_window days)
    ma_preds = []
    for i in range(holdout):
        idx = split_idx + i
        start = max(0, idx - ma_window)
        ma_preds.append(max(0.0, float(np.mean(full_vals[start:idx]))))
    ma_arr = np.array(ma_preds)

    # 3. Random Forest Regression (strictly causal features, chronological split)
    feat_df = build_time_series_features(series).dropna().copy()
    train_feat = feat_df.loc[feat_df.index <= train.index[-1]]
    test_feat = feat_df.loc[feat_df.index > train.index[-1]]

    rf_metrics = None
    rf_model = None
    rf_resid_std = float(np.std(y_true - ma_arr)) if len(y_true) > 1 else 0.5

    if len(train_feat) >= 21 and len(test_feat) >= 5:
        rf_model = RandomForestRegressor(
            n_estimators=120,
            max_depth=6,
            min_samples_leaf=3,
            random_state=random_state,
            n_jobs=1,
        )
        rf_model.fit(train_feat[FEATURE_COLS], train_feat["y"])
        rf_preds = np.clip(rf_model.predict(test_feat[FEATURE_COLS]), 0.0, None)
        rf_true = test_feat["y"].values
        rf_mae = float(mean_absolute_error(rf_true, rf_preds))
        rf_rmse = float(root_mean_squared_error(rf_true, rf_preds))
        rf_resid_std = float(np.std(rf_true - rf_preds)) if len(rf_true) > 1 else 0.5
        rf_metrics = {
            "model_name": "Random Forest Regressor",
            "mae": round(rf_mae, 3),
            "rmse": round(rf_rmse, 3),
            "train_days": int(len(train_feat)),
            "test_days": int(len(test_feat)),
        }

    metrics = [
        {
            "model_name": "Seasonal Naive (Lag-7)",
            "mae": round(float(mean_absolute_error(y_true, naive_arr)), 3),
            "rmse": round(float(root_mean_squared_error(y_true, naive_arr)), 3),
            "train_days": int(len(train)),
            "test_days": int(len(test)),
        },
        {
            "model_name": f"Moving Average ({ma_window}d)",
            "mae": round(float(mean_absolute_error(y_true, ma_arr)), 3),
            "rmse": round(float(root_mean_squared_error(y_true, ma_arr)), 3),
            "train_days": int(len(train)),
            "test_days": int(len(test)),
        },
    ]
    if rf_metrics:
        metrics.append(rf_metrics)

    best = min(metrics, key=lambda m: (m["rmse"], m["mae"]))
    best_std = rf_resid_std if best["model_name"] == "Random Forest Regressor" else float(np.std(y_true - ma_arr))
    if math.isnan(best_std) or best_std <= 0:
        best_std = max(0.25, float(series.std()) * 0.5)

    return {
        "sufficient_data": True,
        "reason": f"Evaluated chronologically on {len(train)} training days and {len(test)} holdout days (no shuffling).",
        "best_model": best["model_name"],
        "best_mae": best["mae"],
        "best_rmse": best["rmse"],
        "metrics": metrics,
        "rf_model": rf_model,
        "residual_std": round(best_std, 3),
    }
