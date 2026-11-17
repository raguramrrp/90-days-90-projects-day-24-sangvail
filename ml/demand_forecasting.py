"""Interpretable demand forecasting engine by blood group and component."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.config import SAVED_MODELS_DIR
from backend.models import BloodComponent, BloodGroup, BloodRequest, ForecastResult
from ml.model_evaluation import (
    FEATURE_COLS,
    build_time_series_features,
    evaluate_models_chronologically,
)


def extract_daily_demand_series(
    session: Session,
    blood_bank_id: Optional[int] = None,
    blood_group: Optional[str] = None,
    component_name: Optional[str] = None,
) -> pd.Series:
    """Aggregate historical daily requested units into a continuous daily time series."""
    stmt = select(BloodRequest).options(
        joinedload(BloodRequest.blood_group),
        joinedload(BloodRequest.component),
    ).where(BloodRequest.status.notin_(["Cancelled", "Rejected"]))

    if blood_bank_id:
        stmt = stmt.where(BloodRequest.blood_bank_id == blood_bank_id)

    reqs = session.scalars(stmt).all()
    rows = []
    for r in reqs:
        if blood_group and blood_group != "All" and r.blood_group.display_name != blood_group:
            continue
        if component_name and component_name != "All" and r.component.component_name != component_name:
            continue
        rows.append({"request_date": pd.Timestamp(r.request_date), "quantity": float(r.required_quantity)})

    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows)
    daily = df.groupby("request_date")["quantity"].sum().sort_index()
    full_idx = pd.date_range(start=daily.index.min(), end=daily.index.max(), freq="D")
    return daily.reindex(full_idx, fill_value=0.0)


def forecast_series(
    daily_series: pd.Series,
    horizon_days: int = 14,
    model_choice: str = "Auto (Best CV RMSE)",
    ma_window: int = 7,
    random_state: int = 42,
    save_artifact_name: Optional[str] = None,
) -> dict:
    """
    Generate non-negative daily forecasts with uncertainty bounds using chronological evaluation.

    Supports:
    - Seasonal Naive (Lag-7)
    - Moving Average (7d)
    - Random Forest Regressor
    - Auto (Best CV RMSE)
    """
    if daily_series.empty:
        return {
            "forecast_df": pd.DataFrame(columns=["forecast_date", "predicted_demand", "lower_bound", "upper_bound"]),
            "history_df": pd.DataFrame(columns=["date", "actual_demand"]),
            "selected_model": "Moving Average (7d)",
            "evaluation": {
                "sufficient_data": False,
                "reason": "No historical demand data available for the selected filters.",
                "metrics": [],
            },
            "data_coverage": "0 days",
            "limitation_note": "No historical records found. Forecast cannot be estimated reliably.",
        }

    series = daily_series.sort_index().astype(float)
    eval_res = evaluate_models_chronologically(series, ma_window=ma_window, random_state=random_state)

    if not eval_res["sufficient_data"]:
        selected_model = f"Moving Average ({ma_window}d)"
        limitation_note = eval_res["reason"]
    elif model_choice == "Auto (Best CV RMSE)":
        selected_model = eval_res["best_model"]
        limitation_note = (
            "Forecasts are statistical estimates derived from historical demand patterns and should "
            "be reviewed alongside scheduled hospital procedures and current inventory."
        )
    else:
        selected_model = model_choice
        limitation_note = (
            "Forecasts are statistical estimates derived from historical demand patterns and should "
            "be reviewed alongside scheduled hospital procedures and current inventory."
        )

    last_date = series.index.max()
    future_dates = [last_date + timedelta(days=i) for i in range(1, horizon_days + 1)]
    resid_std = float(eval_res.get("residual_std", 0.5))

    preds: list[float] = []
    lowers: list[float] = []
    uppers: list[float] = []

    if selected_model.startswith("Random Forest") and len(series) >= 35:
        feat_df = build_time_series_features(series).dropna().copy()
        rf = RandomForestRegressor(
            n_estimators=120,
            max_depth=6,
            min_samples_leaf=3,
            random_state=random_state,
            n_jobs=1,
        )
        rf.fit(feat_df[FEATURE_COLS], feat_df["y"])
        if save_artifact_name:
            SAVED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
            joblib.dump(rf, SAVED_MODELS_DIR / f"{save_artifact_name}.joblib")

        # Recursive multi-step forecast using causal features
        working_series = series.copy()
        for fdt in future_dates:
            idx_val = float(len(working_series))
            lag_1 = float(working_series.iloc[-1])
            lag_7 = float(working_series.iloc[-7]) if len(working_series) >= 7 else lag_1
            lag_14 = float(working_series.iloc[-14]) if len(working_series) >= 14 else lag_7
            roll_7 = float(working_series.iloc[-7:].mean())
            roll_14 = float(working_series.iloc[-14:].mean())
            roll_std_7 = float(working_series.iloc[-7:].std()) if len(working_series) >= 2 else 0.0
            if np.isnan(roll_std_7):
                roll_std_7 = 0.0

            row_x = pd.DataFrame(
                [
                    {
                        "dow": fdt.day_of_week,
                        "day_of_month": fdt.day,
                        "month": fdt.month,
                        "is_weekend": int(fdt.day_of_week >= 5),
                        "lag_1": lag_1,
                        "lag_7": lag_7,
                        "lag_14": lag_14,
                        "roll_mean_7": roll_7,
                        "roll_mean_14": roll_14,
                        "roll_std_7": roll_std_7,
                        "trend_idx": idx_val,
                    }
                ]
            )
            tree_preds = np.array([est.predict(row_x.values)[0] for est in rf.estimators_])
            point = max(0.0, float(np.mean(tree_preds)))
            spread = max(resid_std, float(np.std(tree_preds)))
            lo = max(0.0, point - 1.28 * spread)
            hi = max(point, point + 1.28 * spread)

            preds.append(round(point, 2))
            lowers.append(round(lo, 2))
            uppers.append(round(hi, 2))
            working_series.loc[fdt] = point

    elif selected_model.startswith("Seasonal Naive"):
        vals = series.values
        for step in range(horizon_days):
            idx = len(vals) - 7 + (step % 7)
            point = max(0.0, float(vals[idx])) if idx >= 0 else max(0.0, float(vals[-1]))
            lo = max(0.0, point - 1.28 * resid_std)
            hi = max(point, point + 1.28 * resid_std)
            preds.append(round(point, 2))
            lowers.append(round(lo, 2))
            uppers.append(round(hi, 2))
    else:
        # Moving Average fallback / baseline
        window_mean = max(0.0, float(series.tail(ma_window).mean()))
        for step in range(horizon_days):
            # Subtle horizon uncertainty growth
            horizon_scale = 1.0 + 0.02 * step
            lo = max(0.0, window_mean - 1.28 * resid_std * horizon_scale)
            hi = max(window_mean, window_mean + 1.28 * resid_std * horizon_scale)
            preds.append(round(window_mean, 2))
            lowers.append(round(lo, 2))
            uppers.append(round(hi, 2))

    forecast_df = pd.DataFrame(
        {
            "forecast_date": [d.date() for d in future_dates],
            "predicted_demand": preds,
            "lower_bound": lowers,
            "upper_bound": uppers,
        }
    )
    history_df = pd.DataFrame(
        {
            "date": [d.date() for d in series.index],
            "actual_demand": series.values,
        }
    )
    coverage = f"{series.index.min().date()} to {series.index.max().date()} ({len(series)} days)"
    return {
        "forecast_df": forecast_df,
        "history_df": history_df,
        "selected_model": selected_model,
        "evaluation": eval_res,
        "data_coverage": coverage,
        "limitation_note": limitation_note,
    }


def generate_and_persist_all_forecasts(
    session: Session,
    horizon_days: int = 14,
    blood_bank_id: Optional[int] = None,
    model_choice: str = "Auto (Best CV RMSE)",
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate forecasts across all active blood group & component pairs, persist into
    forecast_results, and return (summary_df, model_eval_by_group_df).
    """
    groups = session.scalars(select(BloodGroup).order_by(BloodGroup.id)).all()
    comps = session.scalars(select(BloodComponent).where(BloodComponent.enabled.is_(True)).order_by(BloodComponent.id)).all()

    session.execute(delete(ForecastResult))
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    summary_rows = []
    group_eval_rows = []

    for comp in comps:
        for bg in groups:
            series = extract_daily_demand_series(
                session,
                blood_bank_id=blood_bank_id,
                blood_group=bg.display_name,
                component_name=comp.component_name,
            )
            if series.empty or float(series.sum()) == 0:
                continue

            res = forecast_series(
                series,
                horizon_days=horizon_days,
                model_choice=model_choice,
                random_state=random_state,
            )
            fdf = res["forecast_df"]
            eval_info = res["evaluation"]
            mae_val = eval_info.get("best_mae")
            rmse_val = eval_info.get("best_rmse")

            for _, row in fdf.iterrows():
                session.add(
                    ForecastResult(
                        blood_group_id=bg.id,
                        component_id=comp.id,
                        forecast_date=row["forecast_date"],
                        predicted_demand=float(row["predicted_demand"]),
                        lower_bound=float(row["lower_bound"]),
                        upper_bound=float(row["upper_bound"]),
                        model_name=res["selected_model"],
                        mae=mae_val,
                        rmse=rmse_val,
                        generated_at=now_utc,
                    )
                )

            summary_rows.append(
                {
                    "blood_group": bg.display_name,
                    "component": comp.component_name,
                    "horizon_days": horizon_days,
                    "forecast_demand": round(float(fdf["predicted_demand"].sum()), 1),
                    "lower_bound_total": round(float(fdf["lower_bound"].sum()), 1),
                    "upper_bound_total": round(float(fdf["upper_bound"].sum()), 1),
                    "model_name": res["selected_model"],
                    "mae": mae_val,
                    "rmse": rmse_val,
                }
            )
            if eval_info.get("metrics"):
                for m in eval_info["metrics"]:
                    group_eval_rows.append(
                        {
                            "blood_group": bg.display_name,
                            "component": comp.component_name,
                            "model_name": m["model_name"],
                            "mae": m["mae"],
                            "rmse": m["rmse"],
                        }
                    )

    session.flush()
    return pd.DataFrame(summary_rows), pd.DataFrame(group_eval_rows)


def get_saved_forecasts_df(session: Session) -> pd.DataFrame:
    """Read persisted forecast results joined with blood group and component names."""
    stmt = (
        select(ForecastResult)
        .options(joinedload(ForecastResult.blood_group), joinedload(ForecastResult.component))
        .order_by(ForecastResult.forecast_date.asc(), ForecastResult.blood_group_id.asc())
    )
    rows = []
    for f in session.scalars(stmt).all():
        rows.append(
            {
                "blood_group": f.blood_group.display_name,
                "component": f.component.component_name,
                "forecast_date": f.forecast_date,
                "predicted_demand": round(f.predicted_demand, 2),
                "lower_bound": round(f.lower_bound, 2),
                "upper_bound": round(f.upper_bound, 2),
                "model_name": f.model_name,
                "mae": f.mae,
                "rmse": f.rmse,
                "generated_at": f.generated_at,
            }
        )
    return pd.DataFrame(rows)
