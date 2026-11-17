# SANGVAIL — Testing & Quality Assurance Report

## Execution Commands

```powershell
# Using Windows batch script
.\test.bat

# Or directly via project virtual environment
.\.venv\Scripts\python.exe -m pytest -v
```

## Verified Automated Test Results

- **Status:** **PASS** (`26 passed in 32.44s`, 0 failures, 0 warnings)
- **Runtime:** Python 3.14.7, Pytest 9.2.0, SQLAlchemy 2.1.9, Streamlit 1.67.0

### Test Matrix

| Test Suite | Tests | Verified Scope | Status |
|---|---:|---|---|
| `tests/test_inventory.py` | 4 | Unit creation, duplicate ID rejection, blood group/component validation, date ordering, state-machine guardrails, stock reconciliation excluding unavailable units | PASS |
| `tests/test_donations.py` | 3 | Donation workflow progression, multi-component production with component-specific shelf lives, rejected donation guard, negative volume validation | PASS |
| `tests/test_screening.py` | 3 | Pending & quarantined units blocked from issuance, rejected units permanently blocked from release, cleared units eligible after authorized release | PASS |
| `tests/test_requests.py` | 3 | Request creation/approval/rejection with mandatory reason, positive quantity validation, over-fulfilment prevention, cancellation stock restoration | PASS |
| `tests/test_allocation.py` | 3 | Strict FEFO earliest-expiry ordering, exclusion of expired/unreleased units, human-approval policy guardrail, double-allocation prevention, shortfall tracking, atomic reversal rollback | PASS |
| `tests/test_expiry.py` | 1 | Per-component configurable warning/critical expiry windows (Platelets vs. RBC), controlled expiry sweep with transaction logs, audited discard without deletion | PASS |
| `tests/test_forecasting.py` | 5 | Deterministic non-negative forecasts, strict chronological holdout evaluation (Seasonal Naive, Moving Average, Random Forest), sparse-history Moving Average fallback, empty series handling, zero-demand coverage safety (`Unavailable`) | PASS |
| `tests/test_data_quality.py` | 2 | Detection of expired-but-released, uncleared-but-released, invalid processing dates, and over-fulfilled requests; controlled audited remediation; ETL duplicate & invalid-row rejection | PASS |
| `tests/test_reports_and_ui.py` | 2 | Seeded database 100% Data Quality audit (`0` critical errors across 8,692 records); CSV, Excel, and ReportLab PDF generation for all 8 reports (PII excluded); Streamlit `AppTest` login + navigation across all 11 pages with 0 exceptions | PASS |

## Known Testing Gaps

- Automated tests execute against isolated temporary SQLite databases and the seeded local SQLite database; PostgreSQL dialect DDL (`database/schema.sql`, `database/views.sql`) was verified structurally against SQLAlchemy 2.0 + `psycopg` driver installation, while live PostgreSQL server execution requires a local PostgreSQL database and credentials in `.env`.
- Browser visual layout was not captured via headless browser automation; manual screenshot capture steps are documented in `screenshots/README.md`.
