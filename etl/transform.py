"""ETL Transform stage: type normalization, date/timestamp parsing, and string cleanup."""

from __future__ import annotations

import pandas as pd


def _parse_date_col(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


def _parse_datetime_col(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def transform_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Normalize types, strip text fields, and prepare validated DataFrames for DB loading."""
    out = {k: v.copy() for k, v in tables.items()}

    if not out["donors"].empty:
        df = out["donors"]
        df["donor_reference"] = df["donor_reference"].astype(str).str.strip()
        df["full_name"] = df["full_name"].astype(str).str.strip()
        df["registration_date"] = _parse_date_col(df["registration_date"])

    if not out["donations"].empty:
        df = out["donations"]
        df["donation_reference"] = df["donation_reference"].astype(str).str.strip()
        df["donor_reference"] = df["donor_reference"].astype(str).str.strip()
        df["donation_date"] = _parse_date_col(df["donation_date"])
        df["collected_quantity"] = df["collected_quantity"].astype(int)
        df["notes"] = df["notes"].fillna("").astype(str)

    if not out["blood_units"].empty:
        df = out["blood_units"]
        df["unit_reference"] = df["unit_reference"].astype(str).str.strip()
        df["collection_date"] = _parse_date_col(df["collection_date"])
        if "processing_date" in df.columns:
            df["processing_date"] = _parse_date_col(df["processing_date"])
        else:
            df["processing_date"] = df["collection_date"]
        df["expiry_date"] = _parse_date_col(df["expiry_date"])

    if not out["screening_records"].empty:
        df = out["screening_records"]
        df["screening_date"] = _parse_date_col(df["screening_date"])
        if "reviewed_at" in df.columns:
            df["reviewed_at"] = _parse_datetime_col(df["reviewed_at"])
        df["reference_note"] = df.get("reference_note", pd.Series("", index=df.index)).fillna("").astype(str)
        df["result_reference"] = df.get("result_reference", pd.Series("LAB-REF", index=df.index)).fillna("LAB-REF").astype(str)

    if not out["blood_requests"].empty:
        df = out["blood_requests"]
        df["request_date"] = _parse_date_col(df["request_date"])
        df["required_date"] = _parse_date_col(df["required_date"])
        df["required_quantity"] = df["required_quantity"].astype(int)
        df["fulfilled_quantity"] = df["fulfilled_quantity"].astype(int)
        df["notes"] = df.get("notes", pd.Series("", index=df.index)).fillna("").astype(str)

    if not out["blood_allocations"].empty:
        df = out["blood_allocations"]
        df["allocation_date"] = _parse_datetime_col(df["allocation_date"])
        if "issue_date" in df.columns:
            df["issue_date"] = _parse_datetime_col(df["issue_date"])
        df["notes"] = df.get("notes", pd.Series("", index=df.index)).fillna("").astype(str)

    if not out["inventory_transactions"].empty:
        df = out["inventory_transactions"]
        df["created_at"] = _parse_datetime_col(df["created_at"])
        df["quantity"] = df["quantity"].astype(int)
        df["reason"] = df.get("reason", pd.Series("", index=df.index)).fillna("").astype(str)

    return out
