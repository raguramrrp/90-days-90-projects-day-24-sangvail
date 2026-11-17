"""ETL Validate stage: column, type, date, duplicate, and referential integrity checks."""

from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd

from app.config import BLOOD_GROUP_NAMES, INVENTORY_STATUSES, REQUEST_URGENCIES

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "donors": ["donor_reference", "full_name", "age_band", "blood_group", "contact", "registration_date", "status"],
    "donations": [
        "donation_reference",
        "donor_reference",
        "blood_bank",
        "donation_date",
        "collection_location",
        "collection_type",
        "collection_status",
        "collected_quantity",
        "collection_staff",
    ],
    "blood_units": [
        "unit_reference",
        "donation_reference",
        "blood_bank",
        "blood_group",
        "component_name",
        "collection_date",
        "expiry_date",
        "screening_status",
        "inventory_status",
        "storage_location",
    ],
    "screening_records": ["screening_reference", "unit_reference", "screening_status", "screening_date"],
    "blood_requests": [
        "request_reference",
        "blood_bank",
        "hospital_name",
        "blood_group",
        "component_name",
        "required_quantity",
        "fulfilled_quantity",
        "urgency",
        "request_date",
        "required_date",
        "status",
    ],
    "blood_allocations": ["request_reference", "unit_reference", "allocation_date", "allocated_by", "allocation_status"],
    "inventory_transactions": [
        "unit_reference",
        "transaction_type",
        "new_status",
        "reference_id",
        "quantity",
        "performed_by",
        "created_at",
    ],
}


@dataclass
class ValidationReport:
    records_extracted: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    duplicate_records: int = 0
    failures: list[str] = field(default_factory=list)
    rejected_rows: dict[str, pd.DataFrame] = field(default_factory=dict)


def validate_extracted_tables(tables: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], ValidationReport]:
    """
    Validate all extracted tables without silently discarding bad rows.

    Returns (accepted_tables, ValidationReport) where every rejected record and reason is tracked.
    """
    report = ValidationReport()
    accepted: dict[str, pd.DataFrame] = {}

    for name, req_cols in REQUIRED_COLUMNS.items():
        if name not in tables:
            report.failures.append(f"Missing table '{name}'")
            accepted[name] = pd.DataFrame(columns=req_cols)
            continue
        df = tables[name].copy()
        report.records_extracted += len(df)
        missing_cols = [c for c in req_cols if c not in df.columns]
        if missing_cols:
            report.failures.append(f"Table '{name}' missing columns: {missing_cols}")
            report.records_rejected += len(df)
            report.rejected_rows[name] = df
            accepted[name] = pd.DataFrame(columns=req_cols)
            continue
        accepted[name] = df

    def _split_invalid(table_name: str, invalid_mask: pd.Series, reason: str, is_dup: bool = False) -> None:
        df = accepted[table_name]
        bad_count = int(invalid_mask.sum())
        if bad_count > 0:
            bad = df[invalid_mask].copy()
            bad["_rejection_reason"] = reason
            prev_bad = report.rejected_rows.get(table_name, pd.DataFrame())
            report.rejected_rows[table_name] = pd.concat([prev_bad, bad], ignore_index=True)
            accepted[table_name] = df[~invalid_mask].copy()
            report.records_rejected += bad_count
            if is_dup:
                report.duplicate_records += bad_count
            report.failures.append(f"{table_name}: {bad_count} row(s) rejected — {reason}")

    # Donors validation
    if not accepted["donors"].empty:
        d = accepted["donors"]
        _split_invalid("donors", d["donor_reference"].isna() | (d["donor_reference"].astype(str).str.strip() == ""), "Missing donor_reference")
        d = accepted["donors"]
        _split_invalid("donors", d.duplicated(subset=["donor_reference"], keep="first"), "Duplicate donor_reference", is_dup=True)
        d = accepted["donors"]
        _split_invalid("donors", ~d["blood_group"].isin(BLOOD_GROUP_NAMES), "Invalid blood group")

    valid_donors = set(accepted["donors"]["donor_reference"].astype(str))

    # Donations validation
    if not accepted["donations"].empty:
        dn = accepted["donations"]
        _split_invalid("donations", dn.duplicated(subset=["donation_reference"], keep="first"), "Duplicate donation_reference", is_dup=True)
        dn = accepted["donations"]
        _split_invalid("donations", ~dn["donor_reference"].astype(str).isin(valid_donors), "Orphan donor_reference")
        dn = accepted["donations"]
        _split_invalid("donations", pd.to_numeric(dn["collected_quantity"], errors="coerce").fillna(0) <= 0, "Non-positive collected_quantity")

    valid_donations = set(accepted["donations"]["donation_reference"].astype(str))

    # Blood units validation
    if not accepted["blood_units"].empty:
        bu = accepted["blood_units"]
        _split_invalid("blood_units", bu.duplicated(subset=["unit_reference"], keep="first"), "Duplicate unit_reference", is_dup=True)
        bu = accepted["blood_units"]
        _split_invalid("blood_units", ~bu["donation_reference"].astype(str).isin(valid_donations), "Orphan donation_reference")
        bu = accepted["blood_units"]
        _split_invalid("blood_units", ~bu["blood_group"].isin(BLOOD_GROUP_NAMES), "Invalid blood_group")
        bu = accepted["blood_units"]
        _split_invalid("blood_units", ~bu["inventory_status"].isin(INVENTORY_STATUSES), "Invalid inventory_status")
        bu = accepted["blood_units"]
        col_dt = pd.to_datetime(bu["collection_date"], errors="coerce")
        exp_dt = pd.to_datetime(bu["expiry_date"], errors="coerce")
        _split_invalid("blood_units", col_dt.isna() | exp_dt.isna() | (exp_dt <= col_dt), "Invalid collection/expiry dates")

    valid_units = set(accepted["blood_units"]["unit_reference"].astype(str))

    # Screening records validation
    if not accepted["screening_records"].empty:
        sc = accepted["screening_records"]
        _split_invalid("screening_records", sc.duplicated(subset=["screening_reference"], keep="first"), "Duplicate screening_reference", is_dup=True)
        sc = accepted["screening_records"]
        _split_invalid("screening_records", ~sc["unit_reference"].astype(str).isin(valid_units), "Orphan unit_reference")

    # Blood requests validation
    if not accepted["blood_requests"].empty:
        br = accepted["blood_requests"]
        _split_invalid("blood_requests", br.duplicated(subset=["request_reference"], keep="first"), "Duplicate request_reference", is_dup=True)
        br = accepted["blood_requests"]
        _split_invalid("blood_requests", ~br["blood_group"].isin(BLOOD_GROUP_NAMES), "Invalid blood_group")
        br = accepted["blood_requests"]
        _split_invalid("blood_requests", ~br["urgency"].isin(REQUEST_URGENCIES), "Invalid urgency")
        br = accepted["blood_requests"]
        req_q = pd.to_numeric(br["required_quantity"], errors="coerce").fillna(0)
        ful_q = pd.to_numeric(br["fulfilled_quantity"], errors="coerce").fillna(-1)
        _split_invalid("blood_requests", (req_q <= 0) | (ful_q < 0) | (ful_q > req_q), "Invalid required/fulfilled quantities")

    valid_requests = set(accepted["blood_requests"]["request_reference"].astype(str))

    # Allocations validation
    if not accepted["blood_allocations"].empty:
        al = accepted["blood_allocations"]
        _split_invalid(
            "blood_allocations",
            (~al["request_reference"].astype(str).isin(valid_requests)) | (~al["unit_reference"].astype(str).isin(valid_units)),
            "Orphan request_reference or unit_reference",
        )

    # Transactions validation
    if not accepted["inventory_transactions"].empty:
        tx = accepted["inventory_transactions"]
        _split_invalid("inventory_transactions", ~tx["unit_reference"].astype(str).isin(valid_units), "Orphan unit_reference")

    report.records_accepted = sum(len(df) for df in accepted.values())
    return accepted, report
