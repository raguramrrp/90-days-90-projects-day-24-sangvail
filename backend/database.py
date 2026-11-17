"""Database engine, session factory, and view bootstrapping for SANGVAIL."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_database_url


class Base(DeclarativeBase):
    """Declarative base for all SANGVAIL SQLAlchemy models."""


def _configure_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a configured SQLAlchemy engine for PostgreSQL or SQLite."""
    url = database_url or get_database_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, echo=False, future=True, connect_args=connect_args, pool_pre_ping=True)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _configure_sqlite_pragma)
    return engine


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine(database_url: str | None = None) -> Engine:
    """Return a cached engine or create one for a custom database URL."""
    global _engine, _SessionLocal
    if database_url:
        return create_db_engine(database_url)
    if _engine is None:
        _engine = create_db_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Dispose and reset cached global engine (useful in tests or config reloads)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Return a SQLAlchemy sessionmaker bound to the active engine."""
    global _SessionLocal
    if engine is not None:
        return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def get_db_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Transactional context manager yielding an ORM Session."""
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_analytics_views(engine: Engine) -> None:
    """Create database analytical views compatible with SQLite and PostgreSQL."""
    is_sqlite = engine.dialect.name == "sqlite"
    month_expr_req = "strftime('%Y-%m', br.request_date)" if is_sqlite else "to_char(br.request_date, 'YYYY-MM')"
    month_expr_tx = "strftime('%Y-%m', it.created_at)" if is_sqlite else "to_char(it.created_at, 'YYYY-MM')"
    today_expr = "date('now')" if is_sqlite else "CURRENT_DATE"
    days_expr = (
        "CAST(julianday(bu.expiry_date) - julianday(date('now')) AS INTEGER)"
        if is_sqlite
        else "(bu.expiry_date - CURRENT_DATE)"
    )

    view_ddls = [
        ("v_current_inventory", f"""
            SELECT
                bu.id AS unit_id,
                bu.unit_reference,
                bb.bank_name,
                bg.display_name AS blood_group,
                bc.component_name,
                bu.collection_date,
                bu.processing_date,
                bu.expiry_date,
                {days_expr} AS remaining_days,
                bu.screening_status,
                bu.inventory_status,
                bu.storage_location
            FROM blood_units bu
            JOIN blood_banks bb ON bb.id = bu.blood_bank_id
            JOIN blood_groups bg ON bg.id = bu.blood_group_id
            JOIN blood_components bc ON bc.id = bu.component_id
        """),
        ("v_blood_group_availability", f"""
            SELECT
                bb.id AS blood_bank_id,
                bb.bank_name,
                bg.display_name AS blood_group,
                bc.component_name,
                COUNT(bu.id) AS total_units,
                SUM(CASE WHEN bu.inventory_status = 'Released' AND bu.expiry_date >= {today_expr} THEN 1 ELSE 0 END) AS available_units,
                SUM(CASE WHEN bu.inventory_status = 'Reserved' THEN 1 ELSE 0 END) AS reserved_units,
                SUM(CASE WHEN bu.inventory_status IN ('Collected', 'Testing Pending') THEN 1 ELSE 0 END) AS pending_screening_units,
                SUM(CASE WHEN bu.inventory_status = 'Quarantined' THEN 1 ELSE 0 END) AS quarantined_units,
                SUM(CASE WHEN bu.inventory_status = 'Issued' THEN 1 ELSE 0 END) AS issued_units,
                SUM(CASE WHEN bu.inventory_status = 'Expired' OR (bu.inventory_status = 'Released' AND bu.expiry_date < {today_expr}) THEN 1 ELSE 0 END) AS expired_units,
                SUM(CASE WHEN bu.inventory_status = 'Discarded' THEN 1 ELSE 0 END) AS discarded_units
            FROM blood_units bu
            JOIN blood_banks bb ON bb.id = bu.blood_bank_id
            JOIN blood_groups bg ON bg.id = bu.blood_group_id
            JOIN blood_components bc ON bc.id = bu.component_id
            GROUP BY bb.id, bb.bank_name, bg.display_name, bc.component_name
        """),
        ("v_monthly_demand", f"""
            SELECT
                {month_expr_req} AS demand_month,
                bg.display_name AS blood_group,
                bc.component_name,
                COUNT(br.id) AS request_count,
                SUM(br.required_quantity) AS total_requested_units,
                SUM(br.fulfilled_quantity) AS total_fulfilled_units,
                SUM(br.required_quantity - br.fulfilled_quantity) AS unfulfilled_units
            FROM blood_requests br
            JOIN blood_groups bg ON bg.id = br.blood_group_id
            JOIN blood_components bc ON bc.id = br.component_id
            WHERE br.status NOT IN ('Cancelled', 'Rejected')
            GROUP BY {month_expr_req}, bg.display_name, bc.component_name
        """),
        ("v_monthly_utilization", f"""
            SELECT
                {month_expr_tx} AS activity_month,
                bg.display_name AS blood_group,
                bc.component_name,
                SUM(CASE WHEN it.transaction_type = 'COLLECTED' THEN it.quantity ELSE 0 END) AS collected_units,
                SUM(CASE WHEN it.transaction_type = 'RELEASED' THEN it.quantity ELSE 0 END) AS released_units,
                SUM(CASE WHEN it.transaction_type = 'ISSUED' THEN it.quantity ELSE 0 END) AS issued_units,
                SUM(CASE WHEN it.transaction_type IN ('EXPIRED', 'DISCARDED') THEN it.quantity ELSE 0 END) AS wastage_units
            FROM inventory_transactions it
            JOIN blood_units bu ON bu.id = it.unit_id
            JOIN blood_groups bg ON bg.id = bu.blood_group_id
            JOIN blood_components bc ON bc.id = bu.component_id
            GROUP BY {month_expr_tx}, bg.display_name, bc.component_name
        """),
        ("v_expiry_exposure", f"""
            SELECT
                bu.id AS unit_id,
                bu.unit_reference,
                bb.bank_name,
                bg.display_name AS blood_group,
                bc.component_name,
                bu.collection_date,
                bu.expiry_date,
                {days_expr} AS remaining_days,
                bu.inventory_status,
                bu.storage_location
            FROM blood_units bu
            JOIN blood_banks bb ON bb.id = bu.blood_bank_id
            JOIN blood_groups bg ON bg.id = bu.blood_group_id
            JOIN blood_components bc ON bc.id = bu.component_id
            WHERE bu.inventory_status IN ('Released', 'Reserved', 'Expired', 'Testing Pending', 'Quarantined')
        """),
        ("v_request_fulfilment", """
            SELECT
                br.id AS request_id,
                br.request_reference,
                h.hospital_name,
                bg.display_name AS blood_group,
                bc.component_name,
                br.urgency,
                br.request_date,
                br.required_date,
                br.required_quantity,
                br.fulfilled_quantity,
                (br.required_quantity - br.fulfilled_quantity) AS remaining_quantity,
                br.status
            FROM blood_requests br
            JOIN hospitals h ON h.id = br.hospital_id
            JOIN blood_groups bg ON bg.id = br.blood_group_id
            JOIN blood_components bc ON bc.id = br.component_id
        """),
        ("v_data_quality_issues", f"""
            SELECT
                'EXPIRED_MARKED_RELEASED' AS issue_code,
                'Critical' AS severity,
                'blood_unit' AS entity_type,
                bu.unit_reference AS entity_reference,
                'Unit is past expiry date but still marked Released' AS description
            FROM blood_units bu
            WHERE bu.inventory_status = 'Released' AND bu.expiry_date < {today_expr}
            UNION ALL
            SELECT
                'INVALID_PROCESSING_DATE' AS issue_code,
                'Critical' AS severity,
                'blood_unit' AS entity_type,
                bu.unit_reference AS entity_reference,
                'Processing date precedes collection date' AS description
            FROM blood_units bu
            WHERE bu.processing_date IS NOT NULL AND bu.processing_date < bu.collection_date
            UNION ALL
            SELECT
                'INVALID_EXPIRY_DATE' AS issue_code,
                'Critical' AS severity,
                'blood_unit' AS entity_type,
                bu.unit_reference AS entity_reference,
                'Expiry date is on or before collection date' AS description
            FROM blood_units bu
            WHERE bu.expiry_date <= bu.collection_date
            UNION ALL
            SELECT
                'OVER_ALLOCATED_REQUEST' AS issue_code,
                'Critical' AS severity,
                'blood_request' AS entity_type,
                br.request_reference AS entity_reference,
                'Fulfilled quantity exceeds required quantity' AS description
            FROM blood_requests br
            WHERE br.fulfilled_quantity > br.required_quantity
        """),
    ]

    with engine.begin() as conn:
        for view_name, select_sql in view_ddls:
            if is_sqlite:
                conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
                conn.execute(text(f"CREATE VIEW {view_name} AS {select_sql}"))
            else:
                conn.execute(text(f"CREATE OR REPLACE VIEW {view_name} AS {select_sql}"))


def _ensure_geo_columns(engine: Engine) -> None:
    """Safely add latitude/longitude columns to existing blood_banks/hospitals tables if missing."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    for tbl, lat_def, lon_def in (
        ("blood_banks", 13.0827, 80.2707),
        ("hospitals", 13.0604, 80.2496),
    ):
        if tbl in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns(tbl)}
            with engine.begin() as conn:
                if "latitude" not in cols:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN latitude FLOAT NOT NULL DEFAULT {lat_def}"))
                if "longitude" not in cols:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN longitude FLOAT NOT NULL DEFAULT {lon_def}"))


def init_db(engine: Engine | None = None) -> Engine:
    """Create all ORM tables and analytical database views."""
    from backend import models  # noqa: F401 — ensures all models register on Base.metadata

    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
    _ensure_geo_columns(eng)
    create_analytics_views(eng)
    return eng


def get_database_status(engine: Engine | None = None) -> dict:
    """Inspect active database backend and connection health."""
    eng = engine or get_engine()
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "connected": True,
            "dialect": eng.dialect.name,
            "driver": eng.dialect.driver,
            "target": str(eng.url.render_as_string(hide_password=True)),
        }
    except Exception as exc:
        return {
            "connected": False,
            "dialect": eng.dialect.name,
            "driver": eng.dialect.driver,
            "target": str(eng.url.render_as_string(hide_password=True)),
            "error": str(exc),
        }
