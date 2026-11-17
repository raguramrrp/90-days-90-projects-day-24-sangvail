"""Read helpers for master reference tables."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import BloodBank, BloodComponent, BloodGroup, Hospital


def get_blood_banks(session: Session) -> list[BloodBank]:
    return list(session.scalars(select(BloodBank).order_by(BloodBank.id.asc())).all())


def get_blood_groups(session: Session) -> list[BloodGroup]:
    return list(session.scalars(select(BloodGroup).order_by(BloodGroup.id.asc())).all())


def get_components(session: Session, only_enabled: bool = False) -> list[BloodComponent]:
    stmt = select(BloodComponent).order_by(BloodComponent.id.asc())
    if only_enabled:
        stmt = stmt.where(BloodComponent.enabled.is_(True))
    return list(session.scalars(stmt).all())


def get_hospitals(session: Session) -> list[Hospital]:
    return list(session.scalars(select(Hospital).order_by(Hospital.hospital_name.asc())).all())
