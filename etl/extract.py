"""ETL Extract stage: read CSV operational datasets safely."""

from __future__ import annotations

from pathlib import Path
import pandas as pd

REQUIRED_CSV_TABLES = [
    "donors",
    "donations",
    "blood_units",
    "screening_records",
    "blood_requests",
    "blood_allocations",
    "inventory_transactions",
]


def extract_csv_directory(source_dir: Path) -> dict[str, pd.DataFrame]:
    """Read expected SANGVAIL CSV tables from a directory."""
    if not source_dir.exists():
        raise FileNotFoundError(f"ETL source directory does not exist: {source_dir}")

    extracted: dict[str, pd.DataFrame] = {}
    for table_name in REQUIRED_CSV_TABLES:
        csv_path = source_dir / f"{table_name}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing required ETL CSV file: {csv_path}")
        extracted[table_name] = pd.read_csv(csv_path, keep_default_na=True)
    return extracted
