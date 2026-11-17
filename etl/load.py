"""ETL Load stage: idempotent relational loader with ETL run audit reporting."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    BLOOD_GROUPS,
    DEFAULT_COMPONENTS,
    DEFAULT_STORAGE_LOCATIONS,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_PATIENT_PASSWORD,
    DEFAULT_PATIENT_USERNAME,
    SYNTHETIC_DATA_DIR,
)
from backend.auth import hash_password
from backend.database import create_analytics_views, get_db_session, init_db
from backend.models import (
    AppSetting,
    BloodAllocation,
    BloodBank,
    BloodComponent,
    BloodGroup,
    BloodRequest,
    BloodUnit,
    Donation,
    Donor,
    ETLRunLog,
    Hospital,
    InventoryTransaction,
    ScreeningRecord,
    StockThreshold,
    User,
)
from etl.extract import extract_csv_directory
from etl.generate_data import BLOOD_BANKS_MASTER, HOSPITALS_MASTER
from etl.transform import transform_tables
from etl.validate import validate_extracted_tables


def seed_master_reference_data(session: Session) -> dict:
    """Ensure master tables, default thresholds, app settings, and demo admin exist."""
    # Blood groups
    bg_map: dict[str, int] = {}
    for abo, rh, disp in BLOOD_GROUPS:
        existing = session.scalar(select(BloodGroup).where(BloodGroup.display_name == disp))
        if not existing:
            existing = BloodGroup(abo_group=abo, rh_factor=rh, display_name=disp)
            session.add(existing)
            session.flush()
        bg_map[disp] = existing.id

    # Blood components
    comp_map: dict[str, int] = {}
    comp_defaults: dict[str, dict] = {}
    for c in DEFAULT_COMPONENTS:
        existing = session.scalar(select(BloodComponent).where(BloodComponent.component_name == c["component_name"]))
        if not existing:
            existing = BloodComponent(
                component_name=c["component_name"],
                short_code=c["short_code"],
                description=c["description"],
                default_shelf_life_days=c["default_shelf_life_days"],
                storage_temp_range=c["storage_temp_range"],
                enabled=c["enabled"],
            )
            session.add(existing)
            session.flush()
        comp_map[c["component_name"]] = existing.id
        comp_defaults[c["component_name"]] = c

    # Blood banks
    bank_map: dict[str, int] = {}
    for b_name, addr, contact, tz, lat, lon in BLOOD_BANKS_MASTER:
        existing = session.scalar(select(BloodBank).where(BloodBank.bank_name == b_name))
        if not existing:
            existing = BloodBank(
                bank_name=b_name, address=addr, contact=contact, timezone=tz,
                latitude=lat, longitude=lon, status="Active",
            )
            session.add(existing)
            session.flush()
        else:
            existing.latitude = lat
            existing.longitude = lon
        bank_map[b_name] = existing.id

    # Hospitals
    hosp_map: dict[str, int] = {}
    for h_name, addr, contact, lat, lon in HOSPITALS_MASTER:
        existing = session.scalar(select(Hospital).where(Hospital.hospital_name == h_name))
        if not existing:
            existing = Hospital(
                hospital_name=h_name, address=addr, contact=contact,
                latitude=lat, longitude=lon, status="Active",
            )
            session.add(existing)
            session.flush()
        else:
            existing.latitude = lat
            existing.longitude = lon
        hosp_map[h_name] = existing.id

    # Stock thresholds (blood_bank x blood_group x component)
    common_groups = {"O+", "A+", "B+"}
    for b_name, b_id in bank_map.items():
        bank_scale = 1.0 if "Central" in b_name else 0.5
        for bg_name, bg_id in bg_map.items():
            for c_name, c_id in comp_map.items():
                exists = session.scalar(
                    select(StockThreshold).where(
                        StockThreshold.blood_bank_id == b_id,
                        StockThreshold.blood_group_id == bg_id,
                        StockThreshold.component_id == c_id,
                    )
                )
                if not exists:
                    base_min = 8 if (bg_name in common_groups and "RBC" in c_name) else (4 if "RBC" in c_name else 3)
                    min_stock = max(2, int(round(base_min * bank_scale)))
                    c_meta = comp_defaults[c_name]
                    session.add(
                        StockThreshold(
                            blood_bank_id=b_id,
                            blood_group_id=bg_id,
                            component_id=c_id,
                            minimum_stock=min_stock,
                            warning_days=c_meta["warning_days"],
                            critical_days=c_meta["critical_days"],
                        )
                    )

    # Default admin user
    admin_user = session.scalar(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    if not admin_user:
        session.add(
            User(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                display_name="Operations Administrator",
                role="Administrator",
                active=True,
            )
        )

    # Default patient/requester user account
    patient_user = session.scalar(select(User).where(User.username == DEFAULT_PATIENT_USERNAME))
    if not patient_user:
        session.add(
            User(
                username=DEFAULT_PATIENT_USERNAME,
                password_hash=hash_password(DEFAULT_PATIENT_PASSWORD),
                display_name="Patient Portal User",
                role="Patient",
                active=True,
            )
        )

    # Default app settings
    defaults = {
        "date_format": "YYYY-MM-DD",
        "number_format": "1,234",
        "default_date_range_days": "90",
        "screening_sla_days": "2",
        "storage_locations": json.dumps(DEFAULT_STORAGE_LOCATIONS),
        "compatibility_policy_mode": "Administrative Exact-Label Match (Non-Clinical)",
    }
    for k, v in defaults.items():
        if not session.scalar(select(AppSetting).where(AppSetting.setting_key == k)):
            session.add(AppSetting(setting_key=k, setting_value=v))

    session.flush()
    return {
        "blood_groups": bg_map,
        "components": comp_map,
        "blood_banks": bank_map,
        "hospitals": hosp_map,
    }


def load_tables_into_db(
    session: Session,
    tables: dict[str, pd.DataFrame],
    source_name: str = "synthetic_csv",
) -> dict:
    """Validate, transform, and load tables into the relational database with ETL reporting."""
    t0 = time.perf_counter()
    accepted, val_report = validate_extracted_tables(tables)
    clean = transform_tables(accepted)
    refs = seed_master_reference_data(session)

    bg_map = refs["blood_groups"]
    comp_map = refs["components"]
    bank_map = refs["blood_banks"]
    hosp_map = refs["hospitals"]
    default_bank_id = next(iter(bank_map.values()))

    # 1. Donors
    existing_donors = {
        d.donor_reference: d.id for d in session.scalars(select(Donor)).all()
    }
    for row in clean["donors"].to_dict("records"):
        ref = row["donor_reference"]
        if ref in existing_donors:
            continue
        obj = Donor(
            donor_reference=ref,
            full_name=row["full_name"],
            age_band=str(row["age_band"]),
            blood_group_id=bg_map[row["blood_group"]],
            contact=str(row["contact"]),
            registration_date=row["registration_date"],
            status=str(row["status"]),
        )
        session.add(obj)
    session.flush()
    donor_map = {d.donor_reference: d.id for d in session.scalars(select(Donor)).all()}

    # 2. Donations
    existing_donations = {
        d.donation_reference: d.id for d in session.scalars(select(Donation)).all()
    }
    for row in clean["donations"].to_dict("records"):
        ref = row["donation_reference"]
        if ref in existing_donations:
            continue
        session.add(
            Donation(
                donation_reference=ref,
                donor_id=donor_map[row["donor_reference"]],
                blood_bank_id=bank_map.get(row["blood_bank"], default_bank_id),
                donation_date=row["donation_date"],
                collection_location=str(row["collection_location"]),
                collection_type=str(row["collection_type"]),
                collection_status=str(row["collection_status"]),
                collected_quantity=int(row["collected_quantity"]),
                collection_staff=str(row["collection_staff"]),
                notes=str(row.get("notes", "")),
                created_by="etl-loader",
            )
        )
    session.flush()
    donation_map = {d.donation_reference: d.id for d in session.scalars(select(Donation)).all()}

    # 3. Blood Units
    existing_units = {u.unit_reference: u.id for u in session.scalars(select(BloodUnit)).all()}
    for row in clean["blood_units"].to_dict("records"):
        ref = row["unit_reference"]
        if ref in existing_units:
            continue
        proc_dt = row.get("processing_date")
        if pd.isna(proc_dt):
            proc_dt = None
        session.add(
            BloodUnit(
                unit_reference=ref,
                donation_id=donation_map[row["donation_reference"]],
                blood_bank_id=bank_map.get(row["blood_bank"], default_bank_id),
                blood_group_id=bg_map[row["blood_group"]],
                component_id=comp_map[row["component_name"]],
                collection_date=row["collection_date"],
                processing_date=proc_dt,
                expiry_date=row["expiry_date"],
                screening_status=str(row["screening_status"]),
                inventory_status=str(row["inventory_status"]),
                storage_location=str(row["storage_location"]),
            )
        )
    session.flush()
    unit_map = {u.unit_reference: u.id for u in session.scalars(select(BloodUnit)).all()}

    # 4. Screening Records
    existing_scr = set(session.scalars(select(ScreeningRecord.screening_reference)).all())
    for row in clean["screening_records"].to_dict("records"):
        ref = str(row["screening_reference"])
        if ref in existing_scr:
            continue
        rev_at = row.get("reviewed_at")
        rev_at_py = None if pd.isna(rev_at) else rev_at.to_pydatetime() if hasattr(rev_at, "to_pydatetime") else rev_at
        rev_by = row.get("reviewed_by")
        rev_by_str = None if pd.isna(rev_by) else str(rev_by)
        session.add(
            ScreeningRecord(
                screening_reference=ref,
                unit_id=unit_map[row["unit_reference"]],
                screening_status=str(row["screening_status"]),
                screening_date=row["screening_date"],
                result_reference=str(row.get("result_reference", "LAB-REF")),
                reviewed_by=rev_by_str,
                reviewed_at=rev_at_py,
                reference_note=str(row.get("reference_note", "")),
            )
        )
    session.flush()

    # 5. Blood Requests
    existing_reqs = {r.request_reference: r.id for r in session.scalars(select(BloodRequest)).all()}
    default_hosp_id = next(iter(hosp_map.values()))
    for row in clean["blood_requests"].to_dict("records"):
        ref = str(row["request_reference"])
        if ref in existing_reqs:
            continue
        session.add(
            BloodRequest(
                request_reference=ref,
                blood_bank_id=bank_map.get(row["blood_bank"], default_bank_id),
                hospital_id=hosp_map.get(row["hospital_name"], default_hosp_id),
                blood_group_id=bg_map[row["blood_group"]],
                component_id=comp_map[row["component_name"]],
                required_quantity=int(row["required_quantity"]),
                fulfilled_quantity=int(row["fulfilled_quantity"]),
                urgency=str(row["urgency"]),
                request_date=row["request_date"],
                required_date=row["required_date"],
                status=str(row["status"]),
                notes=str(row.get("notes", "")),
                created_by=str(row.get("created_by", "etl-loader")),
            )
        )
    session.flush()
    req_map = {r.request_reference: r.id for r in session.scalars(select(BloodRequest)).all()}

    # 6. Blood Allocations
    existing_alloc_pairs = {
        (a.request_id, a.unit_id) for a in session.scalars(select(BloodAllocation)).all()
    }
    for row in clean["blood_allocations"].to_dict("records"):
        r_id = req_map[row["request_reference"]]
        u_id = unit_map[row["unit_reference"]]
        if (r_id, u_id) in existing_alloc_pairs:
            continue
        al_dt = row["allocation_date"]
        al_py = al_dt.to_pydatetime() if hasattr(al_dt, "to_pydatetime") else al_dt
        is_dt = row.get("issue_date")
        is_py = None if pd.isna(is_dt) else is_dt.to_pydatetime() if hasattr(is_dt, "to_pydatetime") else is_dt
        session.add(
            BloodAllocation(
                request_id=r_id,
                unit_id=u_id,
                allocation_date=al_py,
                allocated_by=str(row["allocated_by"]),
                allocation_status=str(row["allocation_status"]),
                issue_date=is_py,
                policy_acknowledged=bool(row.get("policy_acknowledged", True)),
                notes=str(row.get("notes", "")),
            )
        )
    session.flush()

    # 7. Inventory Transactions (load only if table empty or new units added)
    existing_tx_count = session.query(InventoryTransaction).count()
    if existing_tx_count == 0:
        tx_objs = []
        for row in clean["inventory_transactions"].to_dict("records"):
            prev_st = row.get("previous_status")
            prev_str = None if pd.isna(prev_st) else str(prev_st)
            c_at = row["created_at"]
            c_py = c_at.to_pydatetime() if hasattr(c_at, "to_pydatetime") else c_at
            tx_objs.append(
                InventoryTransaction(
                    unit_id=unit_map[row["unit_reference"]],
                    transaction_type=str(row["transaction_type"]),
                    previous_status=prev_str,
                    new_status=str(row["new_status"]),
                    reference_type=str(row.get("reference_type", "UNIT")),
                    reference_id=str(row["reference_id"]),
                    quantity=int(row["quantity"]),
                    reason=str(row.get("reason", "")),
                    performed_by=str(row["performed_by"]),
                    created_at=c_py,
                )
            )
        session.add_all(tx_objs)

    elapsed = round(time.perf_counter() - t0, 3)
    run_ref = f"ETL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    summary_text = "; ".join(val_report.failures) if val_report.failures else "All validation checks passed."
    etl_log = ETLRunLog(
        run_reference=run_ref,
        source_name=source_name,
        records_extracted=val_report.records_extracted,
        records_accepted=val_report.records_accepted,
        records_rejected=val_report.records_rejected,
        duplicate_records=val_report.duplicate_records,
        validation_summary=summary_text,
        execution_seconds=elapsed,
        status="Completed" if val_report.records_rejected == 0 else "Completed with Rejections",
    )
    session.add(etl_log)
    session.flush()

    return {
        "run_reference": run_ref,
        "records_extracted": val_report.records_extracted,
        "records_accepted": val_report.records_accepted,
        "records_rejected": val_report.records_rejected,
        "duplicate_records": val_report.duplicate_records,
        "failures": val_report.failures,
        "execution_seconds": elapsed,
        "status": etl_log.status,
    }


def run_csv_etl_pipeline(source_dir: Optional[Path] = None) -> dict:
    """Execute full Extract -> Validate -> Transform -> Load -> Refresh Views pipeline."""
    eng = init_db()
    src = source_dir or SYNTHETIC_DATA_DIR
    raw_tables = extract_csv_directory(src)
    with get_db_session(eng) as session:
        result = load_tables_into_db(session, raw_tables, source_name=str(src))
    create_analytics_views(eng)
    return result
