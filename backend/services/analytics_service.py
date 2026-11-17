"""Operational overview KPIs, actionable alerts, recent activity, and demand intelligence."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from backend.models import BloodRequest, BloodUnit, InventoryTransaction, StockThreshold
from backend.services.data_quality_service import run_data_quality_checks
from backend.services.expiry_service import get_expiry_monitor_df
from backend.services.inventory_service import get_stock_by_group_and_component, get_stock_reconciliation
from backend.services.request_service import list_requests_df


def get_overview_kpis(
    session: Session,
    blood_bank_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> dict:
    """Compute database-backed summary KPIs for the Overview workstation."""
    today = as_of or date.today()
    month_start = today.replace(day=1)

    recon = get_stock_reconciliation(session, blood_bank_id=blood_bank_id, as_of=today)
    expiry_df = get_expiry_monitor_df(session, blood_bank_id=blood_bank_id, as_of=today)

    approaching_expiry = 0
    if not expiry_df.empty:
        approaching_expiry = int(
            expiry_df[
                expiry_df["inventory_status"].isin(["Released", "Reserved"])
                & expiry_df["expiry_category"].isin(["Critical Window", "Approaching Expiry"])
            ].shape[0]
        )

    req_df = list_requests_df(session, blood_bank_id=blood_bank_id)
    active_requests = 0
    unfulfilled_requests = 0
    if not req_df.empty:
        open_statuses = {"Submitted", "Under Review", "Approved", "Partially Allocated", "Fully Allocated"}
        active_requests = int(req_df[req_df["status"].isin(open_statuses)].shape[0])
        unfulfilled_requests = int(
            req_df[
                req_df["status"].isin({"Submitted", "Under Review", "Approved", "Partially Allocated"})
                & (req_df["remaining_quantity"] > 0)
            ].shape[0]
        )

    tx_stmt = (
        select(InventoryTransaction)
        .join(BloodUnit, BloodUnit.id == InventoryTransaction.unit_id)
        .where(
            InventoryTransaction.transaction_type == "ISSUED",
            InventoryTransaction.created_at >= month_start,
        )
    )
    if blood_bank_id:
        tx_stmt = tx_stmt.where(BloodUnit.blood_bank_id == blood_bank_id)
    issued_this_month = len(session.scalars(tx_stmt).all())

    return {
        "total_released_available": recon["current_available"],
        "pending_screening_units": recon["collected_raw"] + recon["testing_pending"],
        "active_blood_requests": active_requests,
        "units_approaching_expiry": approaching_expiry,
        "unfulfilled_requests": unfulfilled_requests,
        "units_issued_this_month": issued_this_month,
        "reconciliation": recon,
    }


def get_needs_attention_alerts(
    session: Session,
    blood_bank_id: Optional[int] = None,
    as_of: Optional[date] = None,
    screening_sla_days: int = 2,
) -> list[dict]:
    """Generate actionable, database-derived operational attention alerts with page deep-links."""
    today = as_of or date.today()
    alerts: list[dict] = []

    # 1. Below minimum configured stock threshold
    stock_df = get_stock_by_group_and_component(session, blood_bank_id=blood_bank_id, as_of=today)
    stock_lookup: dict[tuple[str, str], int] = {}
    if not stock_df.empty:
        for _, row in stock_df.iterrows():
            stock_lookup[(row["blood_group"], row["component"])] = int(row["available"])

    th_stmt = select(StockThreshold).options(
        joinedload(StockThreshold.blood_group),
        joinedload(StockThreshold.component),
    )
    if blood_bank_id:
        th_stmt = th_stmt.where(StockThreshold.blood_bank_id == blood_bank_id)
    thresholds = session.scalars(th_stmt).all()

    low_stock_items = []
    for t in thresholds:
        bg = t.blood_group.display_name
        comp = t.component.component_name
        avail = stock_lookup.get((bg, comp), 0)
        if avail < t.minimum_stock:
            low_stock_items.append((bg, comp, avail, t.minimum_stock))

    low_stock_items.sort(key=lambda x: (x[2] - x[3], x[2]))
    for bg, comp, avail, min_req in low_stock_items[:5]:
        sev = "Critical" if avail == 0 or avail <= max(1, min_req // 2) else "Warning"
        alerts.append(
            {
                "severity": sev,
                "category": "Low Stock",
                "title": f"{bg} {comp} below minimum threshold ({avail} / {min_req} units)",
                "detail": f"Eligible available stock is {avail} unit(s) against configured floor of {min_req}.",
                "target_page": "Inventory",
                "filter_blood_group": bg,
                "filter_component": comp,
            }
        )

    # 2. Units approaching expiry or expired while still released
    exp_df = get_expiry_monitor_df(session, blood_bank_id=blood_bank_id, as_of=today)
    if not exp_df.empty:
        crit_exp = exp_df[
            exp_df["inventory_status"].isin(["Released", "Reserved"])
            & (exp_df["expiry_category"] == "Critical Window")
        ]
        if not crit_exp.empty:
            alerts.append(
                {
                    "severity": "Critical",
                    "category": "Expiry Exposure",
                    "title": f"{len(crit_exp)} unit(s) in critical expiry window",
                    "detail": "Prioritize FEFO review or discard governance for units nearing component expiry cutoff.",
                    "target_page": "Expiry",
                }
            )
        exp_released = exp_df[(exp_df["inventory_status"] == "Released") & (exp_df["remaining_days"] < 0)]
        if not exp_released.empty:
            alerts.append(
                {
                    "severity": "Critical",
                    "category": "Stock Discrepancy",
                    "title": f"{len(exp_released)} expired unit(s) still marked Released",
                    "detail": "Run controlled expiry transition in Expiry Monitor or Data Quality Centre.",
                    "target_page": "Data Quality",
                }
            )

    # 3. Screening pending beyond configured SLA period
    unit_stmt = select(BloodUnit).where(BloodUnit.inventory_status.in_(["Collected", "Testing Pending"]))
    if blood_bank_id:
        unit_stmt = unit_stmt.where(BloodUnit.blood_bank_id == blood_bank_id)
    pending_units = session.scalars(unit_stmt).all()
    overdue_screening = [u for u in pending_units if (today - u.collection_date).days > screening_sla_days]
    if overdue_screening:
        alerts.append(
            {
                "severity": "Warning",
                "category": "Screening Delay",
                "title": f"{len(overdue_screening)} unit(s) pending screening > {screening_sla_days} days",
                "detail": "Review pending screening queue to release cleared units or quarantine exceptions.",
                "target_page": "Screening",
            }
        )

    # 4. Unfulfilled Urgent / Emergency requests
    req_df = list_requests_df(session, blood_bank_id=blood_bank_id)
    if not req_df.empty:
        urgent_open = req_df[
            req_df["urgency"].isin(["Urgent", "Emergency"])
            & req_df["status"].isin(["Submitted", "Under Review", "Approved", "Partially Allocated"])
            & (req_df["remaining_quantity"] > 0)
        ]
        if not urgent_open.empty:
            alerts.append(
                {
                    "severity": "Critical",
                    "category": "Urgent Requests",
                    "title": f"{len(urgent_open)} unfulfilled Urgent/Emergency request(s)",
                    "detail": f"Total open high-priority shortfall: {int(urgent_open['remaining_quantity'].sum())} unit(s).",
                    "target_page": "Requests",
                }
            )

    # 5. Data quality discrepancies (fast SQL view probe for navigation bar responsiveness)
    try:
        dq_rows = session.execute(text("SELECT severity FROM v_data_quality_issues")).all()
        crit_dq = sum(1 for r in dq_rows if r[0] == "Critical")
        warn_dq = len(dq_rows) - crit_dq
    except Exception:
        dq = run_data_quality_checks(session, blood_bank_id=blood_bank_id, as_of=today)
        crit_dq = dq["critical_error_count"]
        warn_dq = dq["warning_count"]

    if crit_dq > 0 or warn_dq > 0:
        alerts.append(
            {
                "severity": "Critical" if crit_dq > 0 else "Warning",
                "category": "Data Quality",
                "title": f"Data Quality exceptions detected ({crit_dq} critical, {warn_dq} warnings)",
                "detail": "Inspect record-level integrity findings in the Data Quality Centre.",
                "target_page": "Data Quality",
            }
        )

    return alerts


def get_recent_activity_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
    limit: int = 50,
    activity_types: Optional[list[str]] = None,
    blood_groups: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Return chronological recent inventory transaction activity."""
    stmt = (
        select(InventoryTransaction)
        .options(
            joinedload(InventoryTransaction.unit).joinedload(BloodUnit.blood_group),
            joinedload(InventoryTransaction.unit).joinedload(BloodUnit.component),
        )
        .order_by(InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc())
        .limit(limit * 3)
    )
    txs = session.scalars(stmt).all()
    rows = []
    for tx in txs:
        u = tx.unit
        if blood_bank_id and u.blood_bank_id != blood_bank_id:
            continue
        bg = u.blood_group.display_name
        if activity_types and tx.transaction_type not in activity_types:
            continue
        if blood_groups and bg not in blood_groups:
            continue
        rows.append(
            {
                "timestamp": tx.created_at,
                "activity": tx.transaction_type.replace("_", " ").title(),
                "transaction_code": tx.transaction_type,
                "blood_group": bg,
                "component": u.component.component_name,
                "quantity": tx.quantity,
                "unit_reference": u.unit_reference,
                "reference_id": tx.reference_id,
                "responsible_user": tx.performed_by,
                "reason": tx.reason,
            }
        )
        if len(rows) >= limit:
            break
    return pd.DataFrame(rows)


def get_collection_vs_utilization_monthly(
    session: Session,
    blood_bank_id: Optional[int] = None,
    months: int = 12,
) -> pd.DataFrame:
    """Aggregate monthly collection, release, issue, and wastage volumes from transactions."""
    stmt = (
        select(InventoryTransaction)
        .options(joinedload(InventoryTransaction.unit))
        .order_by(InventoryTransaction.created_at.asc())
    )
    txs = session.scalars(stmt).all()
    rows = []
    for tx in txs:
        if blood_bank_id and tx.unit.blood_bank_id != blood_bank_id:
            continue
        rows.append(
            {
                "month": tx.created_at.strftime("%Y-%m"),
                "transaction_type": tx.transaction_type,
                "quantity": tx.quantity,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["month", "collected", "released", "issued", "wastage"])

    df = pd.DataFrame(rows)
    piv = (
        df.pivot_table(index="month", columns="transaction_type", values="quantity", aggfunc="sum", fill_value=0)
        .reset_index()
        .sort_values("month")
    )
    for col in ("COLLECTED", "RELEASED", "ISSUED", "EXPIRED", "DISCARDED"):
        if col not in piv.columns:
            piv[col] = 0
    out = pd.DataFrame(
        {
            "month": piv["month"],
            "collected": piv["COLLECTED"].astype(int),
            "released": piv["RELEASED"].astype(int),
            "issued": piv["ISSUED"].astype(int),
            "wastage": (piv["EXPIRED"] + piv["DISCARDED"]).astype(int),
        }
    )
    return out.tail(months).reset_index(drop=True)


def get_demand_intelligence_bundle(
    session: Session,
    blood_bank_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    blood_groups: Optional[list[str]] = None,
    components: Optional[list[str]] = None,
    hospital_name: Optional[str] = None,
    urgencies: Optional[list[str]] = None,
    statuses: Optional[list[str]] = None,
) -> dict:
    """Compute filtered demand analytics datasets and strictly evidence-based observations."""
    req_df = list_requests_df(
        session,
        blood_bank_id=blood_bank_id,
        blood_groups=blood_groups,
        components=components,
        statuses=statuses,
        urgencies=urgencies,
        hospital_name=hospital_name,
        start_date=start_date,
        end_date=end_date,
    )
    if req_df.empty:
        return {
            "requests_df": req_df,
            "kpis": {
                "total_requested": 0,
                "total_fulfilled": 0,
                "unfulfilled_units": 0,
                "fulfilment_rate_pct": 0.0,
            },
            "monthly_df": pd.DataFrame(),
            "by_group_df": pd.DataFrame(),
            "by_component_df": pd.DataFrame(),
            "heatmap_df": pd.DataFrame(),
            "insights": [],
        }

    valid_df = req_df[~req_df["status"].isin(["Cancelled", "Rejected"])].copy()
    if valid_df.empty:
        valid_df = req_df.copy()

    valid_df["request_dt"] = pd.to_datetime(valid_df["request_date"])
    valid_df["month"] = valid_df["request_dt"].dt.strftime("%Y-%m")
    valid_df["weekday"] = valid_df["request_dt"].dt.day_name()

    total_req = int(valid_df["required_quantity"].sum())
    total_ful = int(valid_df["allocated_quantity"].sum())
    unful = int(valid_df["remaining_quantity"].sum())
    ful_rate = round((total_ful / total_req) * 100.0, 1) if total_req > 0 else 0.0

    monthly_df = (
        valid_df.groupby("month", as_index=False)
        .agg(
            requested_units=("required_quantity", "sum"),
            fulfilled_units=("allocated_quantity", "sum"),
            unfulfilled_units=("remaining_quantity", "sum"),
            request_count=("id", "count"),
        )
        .sort_values("month")
    )
    monthly_df["fulfilment_rate_pct"] = (
        (monthly_df["fulfilled_units"] / monthly_df["requested_units"].replace(0, pd.NA)) * 100.0
    ).fillna(0.0).round(1)

    by_group_df = (
        valid_df.groupby("blood_group", as_index=False)
        .agg(
            requested_units=("required_quantity", "sum"),
            fulfilled_units=("allocated_quantity", "sum"),
            unfulfilled_units=("remaining_quantity", "sum"),
            request_count=("id", "count"),
        )
        .sort_values("requested_units", ascending=False)
    )

    by_component_df = (
        valid_df.groupby("component", as_index=False)
        .agg(
            requested_units=("required_quantity", "sum"),
            fulfilled_units=("allocated_quantity", "sum"),
            unfulfilled_units=("remaining_quantity", "sum"),
        )
        .sort_values("requested_units", ascending=False)
    )

    heatmap_df = valid_df.pivot_table(
        index="blood_group",
        columns="month",
        values="required_quantity",
        aggfunc="sum",
        fill_value=0,
    )

    # Evidence-based observations derived strictly from the active dataset
    insights: list[dict] = []
    min_dt = valid_df["request_date"].min()
    max_dt = valid_df["request_date"].max()
    coverage_str = f"{min_dt} to {max_dt} ({len(valid_df)} requests)"

    # Observation 1: Period-over-period demand change for top blood group
    if len(monthly_df) >= 2:
        last_m = monthly_df.iloc[-1]
        prev_m = monthly_df.iloc[-2]
        if prev_m["requested_units"] > 0:
            pct = ((last_m["requested_units"] - prev_m["requested_units"]) / prev_m["requested_units"]) * 100.0
            direction = "increased" if pct >= 0 else "decreased"
            insights.append(
                {
                    "observation": f"Total monthly blood demand {direction} by {abs(pct):.1f}% in {last_m['month']} compared with {prev_m['month']}.",
                    "period": f"{last_m['month']} vs {prev_m['month']}",
                    "supporting_metric": f"{int(last_m['requested_units'])} units requested",
                    "comparison_baseline": f"{int(prev_m['requested_units'])} units in {prev_m['month']}",
                    "data_coverage": coverage_str,
                }
            )

    # Observation 2: Highest demand blood group share
    if not by_group_df.empty and total_req > 0:
        top_g = by_group_df.iloc[0]
        share = (top_g["requested_units"] / total_req) * 100.0
        avg_group = total_req / len(by_group_df)
        insights.append(
            {
                "observation": f"{top_g['blood_group']} accounted for {share:.1f}% of total requested volume across the selected period.",
                "period": f"{min_dt} to {max_dt}",
                "supporting_metric": f"{int(top_g['requested_units'])} requested units ({int(top_g['unfulfilled_units'])} unfulfilled)",
                "comparison_baseline": f"Mean across {len(by_group_df)} active groups: {avg_group:.1f} units",
                "data_coverage": coverage_str,
            }
        )

    # Observation 3: Highest unfulfilled shortfall group/component
    pair_df = (
        valid_df.groupby(["blood_group", "component"], as_index=False)
        .agg(requested=("required_quantity", "sum"), unfulfilled=("remaining_quantity", "sum"))
        .sort_values("unfulfilled", ascending=False)
    )
    if not pair_df.empty and pair_df.iloc[0]["unfulfilled"] > 0:
        top_u = pair_df.iloc[0]
        gap_pct = (top_u["unfulfilled"] / max(1, top_u["requested"])) * 100.0
        insights.append(
            {
                "observation": (
                    f"{top_u['blood_group']} {top_u['component']} had the largest unfulfilled volume "
                    f"({int(top_u['unfulfilled'])} units; {gap_pct:.1f}% shortfall)."
                ),
                "period": f"{min_dt} to {max_dt}",
                "supporting_metric": f"{int(top_u['unfulfilled'])} unfulfilled / {int(top_u['requested'])} requested",
                "comparison_baseline": f"Overall fulfilment rate: {ful_rate:.1f}%",
                "data_coverage": coverage_str,
            }
        )

    # Observation 4: Collection vs Issue balance over recent 3 months
    util_df = get_collection_vs_utilization_monthly(session, blood_bank_id=blood_bank_id, months=6)
    if len(util_df) >= 2:
        recent_coll = int(util_df.tail(3)["collected"].sum())
        recent_iss = int(util_df.tail(3)["issued"].sum())
        recent_wast = int(util_df.tail(3)["wastage"].sum())
        if recent_coll > 0:
            ratio = recent_iss / recent_coll
            if ratio > 0.85:
                obs = "Recent issue volume closely approached or exceeded new collection intake over the last 3 months."
            else:
                obs = "Collection intake exceeded issued volume over the last 3 months, with wastage requiring ongoing monitoring."
            insights.append(
                {
                    "observation": obs,
                    "period": f"{util_df.tail(3)['month'].iloc[0]} to {util_df.tail(3)['month'].iloc[-1]}",
                    "supporting_metric": f"{recent_coll} collected, {recent_iss} issued, {recent_wast} expired/discarded",
                    "comparison_baseline": f"Issue-to-collection ratio: {ratio:.2f}",
                    "data_coverage": f"Last {min(3, len(util_df))} months of inventory transactions",
                }
            )

    return {
        "requests_df": valid_df,
        "kpis": {
            "total_requested": total_req,
            "total_fulfilled": total_ful,
            "unfulfilled_units": unful,
            "fulfilment_rate_pct": ful_rate,
        },
        "monthly_df": monthly_df,
        "by_group_df": by_group_df,
        "by_component_df": by_component_df,
        "heatmap_df": heatmap_df,
        "insights": insights,
    }
