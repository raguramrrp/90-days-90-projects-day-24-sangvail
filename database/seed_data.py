"""Idempotent database initializer and synthetic demonstration data seeder for SANGVAIL."""

from __future__ import annotations

import sys
from pathlib import Path
from sqlalchemy import func, select

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import SYNTHETIC_DATA_DIR, SYNTHETIC_DATA_SEED
from backend.database import create_analytics_views, get_db_session, init_db
from backend.models import (
    BloodAllocation,
    BloodRequest,
    BloodUnit,
    Donation,
    Donor,
    InventoryTransaction,
    ScreeningRecord,
)
from etl.generate_data import generate_synthetic_dataset
from etl.load import load_tables_into_db, seed_master_reference_data
from ml.demand_forecasting import generate_and_persist_all_forecasts


def seed_database(seed: int = SYNTHETIC_DATA_SEED, export_csv: bool = True) -> dict:
    """
    Initialize schema & views, then populate synthetic demonstration data if empty.

    Preserves existing database records — never drops or wipes an already-populated database.
    """
    engine = init_db()
    with get_db_session(engine) as session:
        seed_master_reference_data(session)
        existing_units = session.scalar(select(func.count(BloodUnit.id))) or 0
        if existing_units > 0:
            return {
                "seeded": False,
                "message": f"Database already contains {existing_units} blood units. Preserved existing data.",
                "counts": {
                    "donors": session.scalar(select(func.count(Donor.id))) or 0,
                    "donations": session.scalar(select(func.count(Donation.id))) or 0,
                    "blood_units": existing_units,
                    "screening_records": session.scalar(select(func.count(ScreeningRecord.id))) or 0,
                    "blood_requests": session.scalar(select(func.count(BloodRequest.id))) or 0,
                    "blood_allocations": session.scalar(select(func.count(BloodAllocation.id))) or 0,
                    "inventory_transactions": session.scalar(select(func.count(InventoryTransaction.id))) or 0,
                },
            }

        tables = generate_synthetic_dataset(seed=seed, export_csv=export_csv, output_dir=SYNTHETIC_DATA_DIR)
        etl_report = load_tables_into_db(session, tables, source_name="synthetic_seed_generator")
        fc_summary, _ = generate_and_persist_all_forecasts(session, horizon_days=14, random_state=seed)

        counts = {
            "donors": session.scalar(select(func.count(Donor.id))) or 0,
            "donations": session.scalar(select(func.count(Donation.id))) or 0,
            "blood_units": session.scalar(select(func.count(BloodUnit.id))) or 0,
            "screening_records": session.scalar(select(func.count(ScreeningRecord.id))) or 0,
            "blood_requests": session.scalar(select(func.count(BloodRequest.id))) or 0,
            "blood_allocations": session.scalar(select(func.count(BloodAllocation.id))) or 0,
            "inventory_transactions": session.scalar(select(func.count(InventoryTransaction.id))) or 0,
            "forecast_series": len(fc_summary),
        }

    create_analytics_views(engine)
    return {
        "seeded": True,
        "message": "SANGVAIL database seeded successfully.",
        "etl_report": etl_report,
        "counts": counts,
    }


if __name__ == "__main__":
    result = seed_database()
    print(result["message"])
    for k, v in result["counts"].items():
        print(f"  - {k}: {v}")
    if "etl_report" in result:
        rep = result["etl_report"]
        print(
            f"ETL Run {rep['run_reference']}: extracted={rep['records_extracted']}, "
            f"accepted={rep['records_accepted']}, rejected={rep['records_rejected']}, "
            f"elapsed={rep['execution_seconds']}s"
        )
