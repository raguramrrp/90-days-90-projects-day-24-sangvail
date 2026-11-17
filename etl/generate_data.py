"""Reproducible 12-month synthetic blood bank operational dataset generator."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import random
import numpy as np
import pandas as pd

from app.config import (
    BLOOD_GROUP_NAMES,
    DEFAULT_COMPONENTS,
    DEFAULT_STORAGE_LOCATIONS,
    DISCARD_REASONS,
    SYNTHETIC_DATA_DIR,
    SYNTHETIC_DATA_SEED,
)

BLOOD_GROUP_WEIGHTS = [0.28, 0.06, 0.14, 0.03, 0.05, 0.02, 0.35, 0.07]  # A+, A-, B+, B-, AB+, AB-, O+, O-
AGE_BANDS = ["18-25", "26-35", "36-45", "46-55", "56-65"]
AGE_WEIGHTS = [0.22, 0.32, 0.24, 0.15, 0.07]

COLLECTION_LOCATIONS = [
    "Central Donor Suite A",
    "Central Donor Suite B",
    "Mobile Blood Drive — Civic Plaza",
    "Mobile Blood Drive — University Campus",
    "North Regional Donor Wing",
]

STAFF_NAMES = [
    "Tech-01",
    "Tech-02",
    "Tech-03",
    "Nurse-04",
    "Nurse-05",
    "QA-Lead-06",
]

HOSPITALS_MASTER = [
    ("Metro Civic Hospital", "100 Civic Way, Metro District", "+000-555-1001", 13.0674, 80.2376),
    ("Harbor General Medical Center", "240 Harbor Blvd, Metro District", "+000-555-1002", 13.0955, 80.2891),
    ("Greenfield Trauma Institute", "55 Greenfield Rd, Central District", "+000-555-1003", 13.0126, 80.2206),
    ("Northside Surgical Center", "410 North Ave, Central District", "+000-555-1004", 13.1288, 80.2544),
    ("Riverview Oncology Unit", "88 Riverview Pkwy, Metro District", "+000-555-1005", 13.0358, 80.2612),
    ("Oakridge Maternal Care Hospital", "19 Oakridge Ln, East Suburb", "+000-555-1006", 12.9891, 80.2495),
]

BLOOD_BANKS_MASTER = [
    ("Sangvail Central Operations", "12 Medical Plaza, Central City", "+000-555-0100", "UTC", 13.0732, 80.2609),
    ("Sangvail North Regional Hub", "84 North Sector, Central City", "+000-555-0200", "UTC", 13.1215, 80.2682),
    ("Sangvail East Trauma Depot", "210 Coastal Medical Corridor", "+000-555-0300", "UTC", 13.0485, 80.2814),
    ("Sangvail South Cold-Chain Hub", "45 Southern Health Park", "+000-555-0400", "UTC", 12.9964, 80.2288),
]


def _storage_for_component(comp_name: str, rng: random.Random) -> str:
    if "Platelets" in comp_name:
        return rng.choice(["Platelet Agitator Unit P1 (20-24°C)", "Platelet Agitator Unit P2 (20-24°C)"])
    if "Plasma" in comp_name or "Cryoprecipitate" in comp_name:
        return rng.choice(["Ultra-Low Freezer F1 (-30°C)", "Ultra-Low Freezer F2 (-30°C)"])
    return rng.choice([
        "Cold Room A — Rack 1 (2-6°C)",
        "Cold Room A — Rack 2 (2-6°C)",
        "Cold Room B — Rack 1 (2-6°C)",
    ])


def generate_synthetic_dataset(
    seed: int = SYNTHETIC_DATA_SEED,
    as_of: date | None = None,
    num_donors: int = 500,
    num_donations: int = 1000,
    num_requests: int = 1200,
    export_csv: bool = True,
    output_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Generate a chronologically consistent, referentially intact 12-month synthetic dataset.

    All names, contacts, IDs, screening references, and hospital entities are strictly
    fictional demonstration placeholders.
    """
    today = as_of or date.today()
    start_day = today - timedelta(days=365)
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    comp_lookup = {c["component_name"]: c for c in DEFAULT_COMPONENTS}

    # 1. Donors (500 fictional records)
    donors = []
    for i in range(1, num_donors + 1):
        bg = rng.choices(BLOOD_GROUP_NAMES, weights=BLOOD_GROUP_WEIGHTS, k=1)[0]
        age_band = rng.choices(AGE_BANDS, weights=AGE_WEIGHTS, k=1)[0]
        reg_offset = rng.randint(0, 720)
        reg_date = start_day - timedelta(days=reg_offset)
        donors.append(
            {
                "donor_reference": f"DNR-{i:04d}",
                "full_name": f"Donor #{i:04d}",
                "age_band": age_band,
                "blood_group": bg,
                "contact": f"donor.{i:04d}@example.invalid",
                "registration_date": reg_date,
                "status": "Active" if rng.random() > 0.04 else "Deferred",
            }
        )
    donors_df = pd.DataFrame(donors)

    # 2. Donations (1,000 records over 365 days with slight seasonal & weekday variation)
    day_candidates = [start_day + timedelta(days=d) for d in range(366)]
    day_weights = []
    for d in day_candidates:
        w = 1.0
        if d.weekday() < 5:
            w *= 1.35
        if d.month in (3, 4, 9, 10, 11):
            w *= 1.15
        if (today - d).days <= 30:
            w *= 1.45  # Healthy recent intake so live stock & screening queue are populated
        day_weights.append(w)

    donation_dates = sorted(rng.choices(day_candidates, weights=day_weights, k=num_donations))
    active_donors = donors_df[donors_df["status"] == "Active"].to_dict("records")

    donations = []
    units = []
    screenings = []
    transactions = []
    unit_counter = 1

    for idx, d_date in enumerate(donation_dates, start=1):
        donor = rng.choice(active_donors)
        bank_name = rng.choices(
            [b[0] for b in BLOOD_BANKS_MASTER],
            weights=[0.46, 0.24, 0.16, 0.14],
            k=1,
        )[0]
        don_ref = f"DN-{idx:05d}"
        days_ago = (today - d_date).days

        # ~6% rejected collections
        is_rejected_collection = rng.random() < 0.06
        if is_rejected_collection:
            col_status = "Rejected"
            qty_ml = rng.choice([200, 250, 300])
            note = "Synthetic collection deferral / insufficient draw volume."
        elif days_ago <= 1 and rng.random() < 0.25:
            col_status = "Processing"
            qty_ml = 450
            note = "Component separation in progress."
        else:
            col_status = "Completed"
            qty_ml = rng.choice([450, 450, 450, 500])
            note = "Standard synthetic collection completed."

        col_type = rng.choices(
            ["Whole Blood Collection", "Apheresis Platelets", "Double RBC Apheresis"],
            weights=[0.80, 0.12, 0.08],
            k=1,
        )[0]
        donations.append(
            {
                "donation_reference": don_ref,
                "donor_reference": donor["donor_reference"],
                "blood_bank": bank_name,
                "blood_group": donor["blood_group"],
                "donation_date": d_date,
                "collection_location": rng.choice(COLLECTION_LOCATIONS),
                "collection_type": col_type,
                "collection_status": col_status,
                "collected_quantity": qty_ml,
                "collection_staff": rng.choice(STAFF_NAMES),
                "notes": note,
            }
        )

        if col_status == "Rejected":
            continue

        # Produce 1-2 blood component units per completed/processing donation (~1,550 total)
        if col_type == "Apheresis Platelets":
            produced_comps = ["Platelets"]
        elif col_type == "Double RBC Apheresis":
            produced_comps = ["Red Blood Cells (RBC)", "Red Blood Cells (RBC)"]
        else:
            roll = rng.random()
            if roll < 0.38:
                produced_comps = ["Red Blood Cells (RBC)", "Fresh Frozen Plasma (FFP)"]
            elif roll < 0.56:
                produced_comps = ["Red Blood Cells (RBC)", "Platelets"]
            elif roll < 0.72:
                produced_comps = ["Red Blood Cells (RBC)"]
            elif roll < 0.85:
                produced_comps = ["Whole Blood"]
            elif roll < 0.94:
                produced_comps = ["Fresh Frozen Plasma (FFP)", "Cryoprecipitate"]
            else:
                produced_comps = ["Red Blood Cells (RBC)", "Fresh Frozen Plasma (FFP)", "Platelets"]

        for comp_name in produced_comps:
            comp_meta = comp_lookup[comp_name]
            unit_ref = f"SV-{unit_counter:05d}"
            unit_counter += 1
            proc_delay = 0 if rng.random() < 0.75 else 1
            proc_date = min(today, d_date + timedelta(days=proc_delay))
            exp_date = d_date + timedelta(days=comp_meta["default_shelf_life_days"])
            storage_loc = _storage_for_component(comp_name, rng)
            staff = rng.choice(STAFF_NAMES)

            # Initial COLLECTED transaction
            collected_ts = datetime.combine(d_date, datetime.min.time()) + timedelta(hours=rng.randint(8, 16))
            transactions.append(
                {
                    "unit_reference": unit_ref,
                    "transaction_type": "COLLECTED",
                    "previous_status": None,
                    "new_status": "Testing Pending",
                    "reference_type": "DONATION",
                    "reference_id": don_ref,
                    "quantity": 1,
                    "reason": f"Unit processed from {don_ref}",
                    "performed_by": staff,
                    "created_at": collected_ts,
                }
            )

            # Determine screening outcome
            scr_date = min(today, proc_date + timedelta(days=rng.choice([0, 1, 1, 2])))
            scr_ts = datetime.combine(scr_date, datetime.min.time()) + timedelta(hours=rng.randint(9, 17))

            # Recent units (last 4 days) may still be Testing Pending (including some >2d for SLA alerts)
            if days_ago <= 4 and rng.random() < 0.42:
                scr_status = "Pending" if days_ago <= 2 else "In Progress"
                inv_status = "Testing Pending"
                reviewed_by = None
                reviewed_at = None
                scr_note = "Awaiting screening clearance."
            else:
                outcome_roll = rng.random()
                if outcome_roll < 0.022:
                    scr_status = "Rejected"
                    inv_status = "Rejected"
                    reviewed_by = rng.choice(STAFF_NAMES)
                    reviewed_at = scr_ts
                    scr_note = "Screening exclusion applied."
                    transactions.append(
                        {
                            "unit_reference": unit_ref,
                            "transaction_type": "REJECTED",
                            "previous_status": "Testing Pending",
                            "new_status": "Rejected",
                            "reference_type": "SCREENING",
                            "reference_id": f"SCR-{unit_ref}",
                            "quantity": 1,
                            "reason": scr_note,
                            "performed_by": reviewed_by,
                            "created_at": scr_ts,
                        }
                    )
                elif outcome_roll < 0.045:
                    scr_status = "Quarantined"
                    inv_status = "Quarantined"
                    storage_loc = "Quarantine Holding Bay Q1"
                    reviewed_by = rng.choice(STAFF_NAMES)
                    reviewed_at = scr_ts
                    scr_note = "Placed on synthetic administrative quarantine hold."
                    transactions.append(
                        {
                            "unit_reference": unit_ref,
                            "transaction_type": "QUARANTINED",
                            "previous_status": "Testing Pending",
                            "new_status": "Quarantined",
                            "reference_type": "SCREENING",
                            "reference_id": f"SCR-{unit_ref}",
                            "quantity": 1,
                            "reason": scr_note,
                            "performed_by": reviewed_by,
                            "created_at": scr_ts,
                        }
                    )
                else:
                    scr_status = "Cleared"
                    inv_status = "Released"
                    reviewed_by = rng.choice(STAFF_NAMES)
                    reviewed_at = scr_ts
                    scr_note = "Synthetic screening cleared for inventory release."
                    transactions.append(
                        {
                            "unit_reference": unit_ref,
                            "transaction_type": "RELEASED",
                            "previous_status": "Testing Pending",
                            "new_status": "Released",
                            "reference_type": "SCREENING",
                            "reference_id": f"SCR-{unit_ref}",
                            "quantity": 1,
                            "reason": scr_note,
                            "performed_by": reviewed_by,
                            "created_at": scr_ts,
                        }
                    )

            screenings.append(
                {
                    "screening_reference": f"SCR-{unit_ref}",
                    "unit_reference": unit_ref,
                    "screening_status": scr_status,
                    "screening_date": scr_date,
                    "result_reference": f"LAB-{unit_counter:05d}",
                    "reviewed_by": reviewed_by,
                    "reviewed_at": reviewed_at,
                    "reference_note": scr_note,
                }
            )
            units.append(
                {
                    "unit_reference": unit_ref,
                    "donation_reference": don_ref,
                    "blood_bank": bank_name,
                    "blood_group": donor["blood_group"],
                    "component_name": comp_name,
                    "collection_date": d_date,
                    "processing_date": proc_date,
                    "expiry_date": exp_date,
                    "screening_status": scr_status,
                    "inventory_status": inv_status,
                    "storage_location": storage_loc,
                    "released_at": scr_ts if inv_status == "Released" else None,
                }
            )

    # 3. Hospital Blood Requests (1,200 requests over 12 months) + FEFO Simulation
    req_day_weights = []
    for d in day_candidates:
        w = 1.0 + 0.25 * np.sin(2 * np.pi * d.timetuple().tm_yday / 365.0)
        if d.weekday() < 5:
            w *= 1.30
        req_day_weights.append(float(max(0.2, w)))

    request_dates = sorted(rng.choices(day_candidates, weights=req_day_weights, k=num_requests))
    comp_req_names = [c["component_name"] for c in DEFAULT_COMPONENTS]
    comp_req_weights = [0.46, 0.22, 0.16, 0.10, 0.06]
    urgencies = ["Routine", "Priority", "Urgent", "Emergency"]
    urgency_weights = [0.58, 0.24, 0.13, 0.05]

    # Index released units by (bank, blood_group, component) for chronological FEFO matching
    released_pool = [u for u in units if u["inventory_status"] == "Released"]
    # Track mutable availability during simulation
    unit_state = {u["unit_reference"]: u for u in units}
    pool_by_key: dict[tuple[str, str, str], list[dict]] = {}
    for u in released_pool:
        key = (u["blood_bank"], u["blood_group"], u["component_name"])
        pool_by_key.setdefault(key, []).append(u)
    for k in pool_by_key:
        pool_by_key[k].sort(key=lambda x: (x["expiry_date"], x["collection_date"], x["unit_reference"]))

    requests = []
    allocations = []

    for r_idx, r_date in enumerate(request_dates, start=1):
        req_ref = f"REQ-{r_idx:05d}"
        bank_name = rng.choices(
            [b[0] for b in BLOOD_BANKS_MASTER],
            weights=[0.46, 0.24, 0.16, 0.14],
            k=1,
        )[0]
        hosp_name = rng.choice(HOSPITALS_MASTER)[0]
        bg = rng.choices(BLOOD_GROUP_NAMES, weights=BLOOD_GROUP_WEIGHTS, k=1)[0]
        comp_name = rng.choices(comp_req_names, weights=comp_req_weights, k=1)[0]
        urgency = rng.choices(urgencies, weights=urgency_weights, k=1)[0]
        req_qty = int(rng.choices([1, 2, 3, 4], weights=[0.52, 0.30, 0.12, 0.06], k=1)[0])
        lead = 0 if urgency in ("Emergency", "Urgent") else rng.randint(1, 4)
        req_by_date = r_date + timedelta(days=lead)
        days_since_req = (today - r_date).days
        actor = rng.choice(STAFF_NAMES)

        # ~4% cancelled or rejected before allocation
        if rng.random() < 0.04:
            status = rng.choice(["Cancelled", "Rejected"])
            requests.append(
                {
                    "request_reference": req_ref,
                    "blood_bank": bank_name,
                    "hospital_name": hosp_name,
                    "blood_group": bg,
                    "component_name": comp_name,
                    "required_quantity": req_qty,
                    "fulfilled_quantity": 0,
                    "urgency": urgency,
                    "request_date": r_date,
                    "required_date": req_by_date,
                    "status": status,
                    "notes": f"Synthetic request {status.lower()} by hospital coordination.",
                    "created_by": actor,
                }
            )
            continue

        # Leave a subset of very recent requests (last 3 days) open in Submitted/Approved/Partially Allocated
        if days_since_req <= 2 and rng.random() < 0.55:
            open_status = rng.choice(["Submitted", "Under Review", "Approved"])
            requests.append(
                {
                    "request_reference": req_ref,
                    "blood_bank": bank_name,
                    "hospital_name": hosp_name,
                    "blood_group": bg,
                    "component_name": comp_name,
                    "required_quantity": req_qty,
                    "fulfilled_quantity": 0,
                    "urgency": urgency,
                    "request_date": r_date,
                    "required_date": req_by_date,
                    "status": open_status,
                    "notes": "Open hospital blood request awaiting FEFO allocation.",
                    "created_by": actor,
                }
            )
            continue

        # Chronological FEFO match: unit must be released on or before r_date, not expired on r_date, still Released
        candidates = pool_by_key.get((bank_name, bg, comp_name), [])
        matched = []
        for u in candidates:
            if u["inventory_status"] != "Released":
                continue
            rel_dt = u["released_at"].date() if u["released_at"] else u["collection_date"]
            if rel_dt <= r_date <= u["expiry_date"]:
                matched.append(u)
                if len(matched) == req_qty:
                    break

        fulfilled_qty = len(matched)
        alloc_ts = datetime.combine(r_date, datetime.min.time()) + timedelta(hours=rng.randint(8, 18))

        # Historical requests (>3 days ago) with allocations are Issued; recent ones may stay Reserved
        should_issue = days_since_req > 3 or (days_since_req <= 3 and rng.random() < 0.45)

        if fulfilled_qty == 0:
            req_status = "Approved" if days_since_req <= 10 else "Closed"
            req_note = "Insufficient eligible stock at request time."
        else:
            for u in matched:
                u["inventory_status"] = "Reserved"
                transactions.append(
                    {
                        "unit_reference": u["unit_reference"],
                        "transaction_type": "RESERVED",
                        "previous_status": "Released",
                        "new_status": "Reserved",
                        "reference_type": "REQUEST",
                        "reference_id": req_ref,
                        "quantity": 1,
                        "reason": f"FEFO reserved for {req_ref}",
                        "performed_by": actor,
                        "created_at": alloc_ts,
                    }
                )
                if should_issue:
                    issue_ts = alloc_ts + timedelta(hours=rng.randint(1, 6))
                    u["inventory_status"] = "Issued"
                    alloc_status = "Issued"
                    transactions.append(
                        {
                            "unit_reference": u["unit_reference"],
                            "transaction_type": "ISSUED",
                            "previous_status": "Reserved",
                            "new_status": "Issued",
                            "reference_type": "REQUEST",
                            "reference_id": req_ref,
                            "quantity": 1,
                            "reason": f"Issued to {hosp_name} for {req_ref}",
                            "performed_by": actor,
                            "created_at": issue_ts,
                        }
                    )
                else:
                    issue_ts = None
                    alloc_status = "Reserved"

                allocations.append(
                    {
                        "request_reference": req_ref,
                        "unit_reference": u["unit_reference"],
                        "allocation_date": alloc_ts,
                        "allocated_by": actor,
                        "allocation_status": alloc_status,
                        "issue_date": issue_ts,
                        "policy_acknowledged": True,
                        "notes": "FEFO allocation.",
                    }
                )

            if should_issue:
                req_status = "Issued"
                req_note = "Units handed over to hospital."
            elif fulfilled_qty == req_qty:
                req_status = "Fully Allocated"
                req_note = "Fully reserved via FEFO awaiting handover."
            else:
                req_status = "Partially Allocated"
                req_note = f"Partially allocated ({fulfilled_qty}/{req_qty}); shortfall pending replenishment."

        requests.append(
            {
                "request_reference": req_ref,
                "blood_bank": bank_name,
                "hospital_name": hosp_name,
                "blood_group": bg,
                "component_name": comp_name,
                "required_quantity": req_qty,
                "fulfilled_quantity": fulfilled_qty,
                "urgency": urgency,
                "request_date": r_date,
                "required_date": req_by_date,
                "status": req_status,
                "notes": req_note,
                "created_by": actor,
            }
        )

    # 4. Expire & Discard unissued units whose expiry_date < today (ensuring ZERO expired units remain Released!)
    for u in units:
        if u["inventory_status"] in ("Released", "Testing Pending", "Quarantined") and u["expiry_date"] < today:
            prev_st = u["inventory_status"]
            exp_ts = datetime.combine(u["expiry_date"] + timedelta(days=1), datetime.min.time()) + timedelta(hours=7)
            u["inventory_status"] = "Expired"
            transactions.append(
                {
                    "unit_reference": u["unit_reference"],
                    "transaction_type": "EXPIRED",
                    "previous_status": prev_st,
                    "new_status": "Expired",
                    "reference_type": "EXPIRY_SWEEP",
                    "reference_id": u["expiry_date"].isoformat(),
                    "quantity": 1,
                    "reason": "Expired while unused in storage",
                    "performed_by": "system-expiry-job",
                    "created_at": exp_ts,
                }
            )
            # Most older expired units (>7 days past expiry) have been properly discarded with reason
            if (today - u["expiry_date"]).days > 7 and rng.random() < 0.72:
                disc_ts = exp_ts + timedelta(days=rng.randint(1, 3))
                u["inventory_status"] = "Discarded"
                transactions.append(
                    {
                        "unit_reference": u["unit_reference"],
                        "transaction_type": "DISCARDED",
                        "previous_status": "Expired",
                        "new_status": "Discarded",
                        "reference_type": "DISCARD",
                        "reference_id": u["unit_reference"],
                        "quantity": 1,
                        "reason": DISCARD_REASONS[0],
                        "performed_by": rng.choice(STAFF_NAMES),
                        "created_at": disc_ts,
                    }
                )
        elif u["inventory_status"] == "Rejected" and (today - u["collection_date"]).days > 14 and rng.random() < 0.65:
            disc_ts = datetime.combine(u["collection_date"] + timedelta(days=5), datetime.min.time()) + timedelta(hours=14)
            u["inventory_status"] = "Discarded"
            transactions.append(
                {
                    "unit_reference": u["unit_reference"],
                    "transaction_type": "DISCARDED",
                    "previous_status": "Rejected",
                    "new_status": "Discarded",
                    "reference_type": "DISCARD",
                    "reference_id": u["unit_reference"],
                    "quantity": 1,
                    "reason": DISCARD_REASONS[3],
                    "performed_by": rng.choice(STAFF_NAMES),
                    "created_at": disc_ts,
                }
            )

    units_df = pd.DataFrame([{k: v for k, v in u.items() if k != "released_at"} for u in units])
    donations_df = pd.DataFrame(donations)
    screenings_df = pd.DataFrame(screenings)
    requests_df = pd.DataFrame(requests)
    allocations_df = pd.DataFrame(allocations)
    transactions_df = pd.DataFrame(transactions)

    datasets = {
        "donors": donors_df,
        "donations": donations_df,
        "blood_units": units_df,
        "screening_records": screenings_df,
        "blood_requests": requests_df,
        "blood_allocations": allocations_df,
        "inventory_transactions": transactions_df,
    }

    if export_csv:
        target_dir = output_dir or SYNTHETIC_DATA_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        for name, df in datasets.items():
            df.to_csv(target_dir / f"{name}.csv", index=False)

    return datasets


if __name__ == "__main__":
    data = generate_synthetic_dataset(export_csv=True)
    for table_name, df in data.items():
        print(f"{table_name}: {len(df)} rows")
