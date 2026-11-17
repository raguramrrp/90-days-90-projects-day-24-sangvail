# SANGVAIL Synthetic Demonstration Dataset

## Origin & License

All datasets in `data/synthetic/` and `data/sangvail.db` are **100% synthetically generated** by `etl/generate_data.py` using a deterministic random seed (`SYNTHETIC_DATA_SEED=42`). No real donor, patient, clinical laboratory, or hospital records are used anywhere in this repository.

Synthetic donor identities use fictional placeholders (`Demo Donor #0001`, `demo.donor.0001@example.invalid`) so they cannot correspond to real individuals.

## Generated Record Volumes (Default Seed = 42, 12-Month Window)

| Table | Approximate Rows | Description |
|---|---:|---|
| `donors.csv` | 500 | Fictional donor profiles across all 8 ABO/Rh blood groups |
| `donations.csv` | 1,000 | 12-month collection history with seasonality, weekday bias, and ~6% rejections |
| `blood_units.csv` | ~1,632 | Individual blood units across RBC, Platelets, FFP, Whole Blood, Cryoprecipitate |
| `screening_records.csv` | ~1,632 | Fictional operational screening & release dispositions |
| `blood_requests.csv` | 1,200 | Hospital requests across 6 fictional hospitals and 4 administrative urgency levels |
| `blood_allocations.csv` | ~1,031 | Chronologically consistent FEFO unit reservations and issues |
| `inventory_transactions.csv` | ~5,860 | Complete immutable unit custody ledger (`COLLECTED`, `RELEASED`, `RESERVED`, `ISSUED`, `EXPIRED`, `DISCARDED`) |

## Regeneration Instructions

```powershell
.\.venv\Scripts\python.exe etl\generate_data.py
```

To validate and load generated CSVs through the ETL pipeline:

```powershell
.\.venv\Scripts\python.exe -c "from etl.load import run_csv_etl_pipeline; print(run_csv_etl_pipeline())"
```
