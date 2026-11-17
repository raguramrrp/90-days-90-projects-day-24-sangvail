"""Explainable rules-based shortage planning intelligence."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.models import BloodComponent, BloodGroup, BloodRequest, ForecastResult, StockThreshold
from backend.services.expiry_service import get_expiry_monitor_df
from backend.services.inventory_service import get_stock_by_group_and_component


def compute_shortage_planning_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
    horizon_days: int = 14,
    lookback_days: int = 90,
    as_of: Optional[date] = None,
) -> pd.DataFrame:
    """
    Compute transparent, rules-based planning status for each blood group & component.

    Planning statuses (Critical, High, Moderate, Stable) are strictly operational inventory
    planning indicators — NOT clinical risk classifications.
    """
    today = as_of or date.today()
    lookback_start = today - timedelta(days=lookback_days)

    groups = session.scalars(select(BloodGroup).order_by(BloodGroup.id)).all()
    comps = session.scalars(select(BloodComponent).where(BloodComponent.enabled.is_(True)).order_by(BloodComponent.id)).all()

    # 1. Eligible available stock
    stock_df = get_stock_by_group_and_component(session, blood_bank_id=blood_bank_id, as_of=today)
    avail_map = {
        (r["blood_group"], r["component"]): int(r["available"])
        for _, r in stock_df.iterrows()
    } if not stock_df.empty else {}

    # 2. Near-expiry eligible stock
    exp_df = get_expiry_monitor_df(session, blood_bank_id=blood_bank_id, as_of=today)
    near_exp_map: dict[tuple[str, str], int] = {}
    if not exp_df.empty:
        near = exp_df[
            (exp_df["inventory_status"] == "Released")
            & (exp_df["expiry_category"].isin(["Critical Window", "Approaching Expiry"]))
        ]
        for (bg, comp), grp in near.groupby(["blood_group", "component"]):
            near_exp_map[(bg, comp)] = int(len(grp))

    # 3. Open request quantities & historical average daily demand
    req_stmt = select(BloodRequest).options(
        joinedload(BloodRequest.blood_group),
        joinedload(BloodRequest.component),
    )
    if blood_bank_id:
        req_stmt = req_stmt.where(BloodRequest.blood_bank_id == blood_bank_id)
    reqs = session.scalars(req_stmt).all()

    open_req_map: dict[tuple[str, str], int] = {}
    hist_qty_map: dict[tuple[str, str], int] = {}
    open_statuses = {"Submitted", "Under Review", "Approved", "Partially Allocated"}

    for r in reqs:
        key = (r.blood_group.display_name, r.component.component_name)
        if r.status in open_statuses:
            rem = max(0, r.required_quantity - r.fulfilled_quantity)
            open_req_map[key] = open_req_map.get(key, 0) + rem
        if r.status not in ("Cancelled", "Rejected") and r.request_date >= lookback_start:
            hist_qty_map[key] = hist_qty_map.get(key, 0) + r.required_quantity

    # 4. Persisted forecast demand over horizon
    fc_end = today + timedelta(days=horizon_days)
    fc_stmt = select(ForecastResult).options(
        joinedload(ForecastResult.blood_group),
        joinedload(ForecastResult.component),
    ).where(ForecastResult.forecast_date <= fc_end)
    fc_map: dict[tuple[str, str], float] = {}
    for f in session.scalars(fc_stmt).all():
        key = (f.blood_group.display_name, f.component.component_name)
        fc_map[key] = fc_map.get(key, 0.0) + float(f.predicted_demand)

    # 5. Configured minimum stock thresholds
    th_stmt = select(StockThreshold).options(
        joinedload(StockThreshold.blood_group),
        joinedload(StockThreshold.component),
    )
    if blood_bank_id:
        th_stmt = th_stmt.where(StockThreshold.blood_bank_id == blood_bank_id)
    min_stock_map: dict[tuple[str, str], int] = {}
    for t in session.scalars(th_stmt).all():
        key = (t.blood_group.display_name, t.component.component_name)
        min_stock_map[key] = min_stock_map.get(key, 0) + int(t.minimum_stock)

    rows = []
    for comp in comps:
        for bg in groups:
            key = (bg.display_name, comp.component_name)
            avail = avail_map.get(key, 0)
            open_qty = open_req_map.get(key, 0)
            hist_total = hist_qty_map.get(key, 0)
            avg_daily = round(hist_total / float(lookback_days), 2)
            near_exp = near_exp_map.get(key, 0)
            min_stock = min_stock_map.get(key, 5)
            fc_demand = round(fc_map.get(key, avg_daily * horizon_days), 1)

            if avg_daily > 0:
                coverage_days_num: Optional[float] = round(avail / avg_daily, 1)
                coverage_label = f"{coverage_days_num:.1f} days"
            else:
                coverage_days_num = None
                coverage_label = "Unavailable (0 demand)"

            # Transparent rule-based classification & human-readable explanation
            reasons = []
            score = 0
            if avail < min_stock:
                score += 40 if avail <= max(1, min_stock // 2) else 25
                reasons.append(f"available stock ({avail}) is below configured minimum ({min_stock})")
            if open_qty > avail:
                score += 35
                reasons.append(f"open requests ({open_qty}) exceed current unreserved stock ({avail})")
            elif open_qty > 0 and (avail - open_qty) < min_stock:
                score += 15
                reasons.append(f"fulfilling open requests ({open_qty}) would leave stock below minimum")
            if coverage_days_num is not None:
                if coverage_days_num < 3.0:
                    score += 30
                    reasons.append(f"estimated coverage ({coverage_days_num:.1f}d) is under 3 days")
                elif coverage_days_num < 7.0:
                    score += 15
                    reasons.append(f"estimated coverage ({coverage_days_num:.1f}d) is under 7 days")
            if fc_demand > 0 and avail < fc_demand:
                score += 15
                reasons.append(f"current stock ({avail}) is below {horizon_days}-day forecast demand ({fc_demand:.1f})")
            if near_exp > 0 and avail > 0 and (near_exp / avail) >= 0.4:
                score += 10
                reasons.append(f"{near_exp} of {avail} available units are nearing expiry")

            if score >= 65 or (avail == 0 and (open_qty > 0 or min_stock > 0)):
                status = "Critical"
            elif score >= 40:
                status = "High"
            elif score >= 20:
                status = "Moderate"
            else:
                status = "Stable"

            if reasons:
                explanation = f"{status} planning alert: " + "; ".join(reasons) + "."
            else:
                explanation = "Stable: eligible inventory exceeds minimum floor, open requests, and near-term forecast."

            rows.append(
                {
                    "blood_group": bg.display_name,
                    "component": comp.component_name,
                    "eligible_stock": avail,
                    "open_requests": open_qty,
                    "near_expiry_units": near_exp,
                    "avg_daily_demand": avg_daily,
                    "coverage_days": coverage_label,
                    "coverage_days_num": coverage_days_num,
                    "minimum_stock": min_stock,
                    "forecast_demand": fc_demand,
                    "planning_score": min(100, score),
                    "planning_status": status,
                    "explanation": explanation,
                }
            )

    df = pd.DataFrame(rows)
    status_order = {"Critical": 0, "High": 1, "Moderate": 2, "Stable": 3}
    if not df.empty:
        df["_ord"] = df["planning_status"].map(status_order)
        df = df.sort_values(["_ord", "planning_score", "blood_group"], ascending=[True, False, True]).drop(columns=["_ord"])
    return df.reset_index(drop=True)
