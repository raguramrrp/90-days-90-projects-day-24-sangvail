"""Settings, blood bank configuration, component policies, and stock threshold management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import DEFAULT_STORAGE_LOCATIONS
from backend.auth import log_audit
from backend.models import AppSetting, BloodBank, BloodComponent, StockThreshold
from backend.schemas import ThresholdUpdate


def get_setting(session: Session, key: str, default: str = "") -> str:
    row = session.scalar(select(AppSetting).where(AppSetting.setting_key == key))
    return row.setting_value if row else default


def set_setting(session: Session, key: str, value: str, actor: str = "admin") -> AppSetting:
    row = session.scalar(select(AppSetting).where(AppSetting.setting_key == key))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row:
        row.setting_value = value
        row.updated_at = now
    else:
        row = AppSetting(setting_key=key, setting_value=value, updated_at=now)
        session.add(row)
    log_audit(
        session,
        action="UPDATE_SETTING",
        entity_type="app_setting",
        entity_id=key,
        details=f"Updated setting '{key}'",
        actor_name=actor,
    )
    return row


def get_storage_locations(session: Session) -> list[str]:
    raw = get_setting(session, "storage_locations", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return [str(x) for x in parsed]
        except Exception:
            pass
    return list(DEFAULT_STORAGE_LOCATIONS)


def save_storage_locations(session: Session, locations: list[str], actor: str = "admin") -> list[str]:
    cleaned = [loc.strip() for loc in locations if loc.strip()]
    set_setting(session, "storage_locations", json.dumps(cleaned), actor=actor)
    return cleaned


def update_blood_bank_profile(
    session: Session,
    bank_id: int,
    bank_name: str,
    address: str,
    contact: str,
    timezone_name: str,
    actor: str = "admin",
) -> BloodBank:
    bank = session.get(BloodBank, bank_id)
    if not bank:
        raise ValueError(f"Blood bank ID {bank_id} not found.")
    bank.bank_name = bank_name.strip()
    bank.address = address.strip()
    bank.contact = contact.strip()
    bank.timezone = timezone_name.strip()
    log_audit(
        session,
        action="UPDATE_BLOOD_BANK",
        entity_type="blood_bank",
        entity_id=str(bank.id),
        details=f"Updated bank profile: {bank.bank_name} ({bank.timezone})",
        actor_name=actor,
    )
    return bank


def update_component_policy(
    session: Session,
    component_id: int,
    default_shelf_life_days: int,
    storage_temp_range: str,
    enabled: bool,
    actor: str = "admin",
) -> BloodComponent:
    comp = session.get(BloodComponent, component_id)
    if not comp:
        raise ValueError(f"Component ID {component_id} not found.")
    if default_shelf_life_days <= 0:
        raise ValueError("Default shelf life days must be positive.")
    comp.default_shelf_life_days = default_shelf_life_days
    comp.storage_temp_range = storage_temp_range.strip()
    comp.enabled = enabled
    log_audit(
        session,
        action="UPDATE_COMPONENT_POLICY",
        entity_type="blood_component",
        entity_id=comp.component_name,
        details=f"Shelf life={default_shelf_life_days}d, temp={storage_temp_range}, enabled={enabled}",
        actor_name=actor,
    )
    return comp


def list_thresholds_df(session: Session, blood_bank_id: Optional[int] = None) -> pd.DataFrame:
    stmt = (
        select(StockThreshold)
        .options(
            joinedload(StockThreshold.blood_bank),
            joinedload(StockThreshold.blood_group),
            joinedload(StockThreshold.component),
        )
        .order_by(StockThreshold.blood_bank_id.asc(), StockThreshold.component_id.asc(), StockThreshold.blood_group_id.asc())
    )
    if blood_bank_id:
        stmt = stmt.where(StockThreshold.blood_bank_id == blood_bank_id)
    rows = []
    for t in session.scalars(stmt).all():
        rows.append(
            {
                "id": t.id,
                "blood_bank_id": t.blood_bank_id,
                "blood_bank": t.blood_bank.bank_name,
                "blood_group_id": t.blood_group_id,
                "blood_group": t.blood_group.display_name,
                "component_id": t.component_id,
                "component": t.component.component_name,
                "minimum_stock": t.minimum_stock,
                "warning_days": t.warning_days,
                "critical_days": t.critical_days,
            }
        )
    return pd.DataFrame(rows)


def upsert_stock_threshold(session: Session, payload: ThresholdUpdate, actor: str = "admin") -> StockThreshold:
    existing = session.scalar(
        select(StockThreshold).where(
            StockThreshold.blood_bank_id == payload.blood_bank_id,
            StockThreshold.blood_group_id == payload.blood_group_id,
            StockThreshold.component_id == payload.component_id,
        )
    )
    if existing:
        existing.minimum_stock = payload.minimum_stock
        existing.warning_days = payload.warning_days
        existing.critical_days = payload.critical_days
        row = existing
    else:
        row = StockThreshold(
            blood_bank_id=payload.blood_bank_id,
            blood_group_id=payload.blood_group_id,
            component_id=payload.component_id,
            minimum_stock=payload.minimum_stock,
            warning_days=payload.warning_days,
            critical_days=payload.critical_days,
        )
        session.add(row)
    session.flush()
    log_audit(
        session,
        action="UPSERT_STOCK_THRESHOLD",
        entity_type="stock_threshold",
        entity_id=f"bank={payload.blood_bank_id},bg={payload.blood_group_id},comp={payload.component_id}",
        details=f"min={payload.minimum_stock}, warn={payload.warning_days}d, crit={payload.critical_days}d",
        actor_name=actor,
    )
    return row
