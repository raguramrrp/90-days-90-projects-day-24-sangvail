# SANGVAIL — Blood Bank Inventory, Operations & Demand Intelligence Platform

> *Day 24 — 90 Days – 90 Projects Challenge (Healthcare Technology · Data Engineering · Predictive Analytics)*

SANGVAIL is a centralized blood bank operations and resource-intelligence workstation built with Python, Streamlit, SQLAlchemy 2.0, PostgreSQL (with zero-configuration SQLite fallback), Scikit-learn, Plotly, and ReportLab. It tracks individual blood units across their complete operational lifecycle—from synthetic donation intake and controlled screening release to First Expiry, First Out (FEFO) hospital allocation, expiry governance, chronological demand forecasting, and automated 14-check data quality auditing.

> **Healthcare Safety & Synthetic Data Disclaimer:** SANGVAIL is an **educational prototype using 100% synthetic demonstration data**. It is **not** a certified blood bank management system, medical device, laboratory information system (LIS), or clinical transfusion decision tool. Never use it with real donor or patient data or to make clinical compatibility decisions.

---

## 1. Problem Statement & Motivation

Blood components have sharply divergent shelf lives (e.g., 5 days for Platelets, 35–42 days for Whole Blood / RBCs, 365 days for Fresh Frozen Plasma) and strict custody requirements. Managing stock through aggregate spreadsheets or simple subtraction (`donations - requests`) creates silent operational errors:

- Unscreened, quarantined, or expired units accidentally appear as available stock.
- Reserved units get double-allocated across concurrent hospital requests.
- Short-shelf-life components expire unused while near-term demand spikes go unnoticed.

SANGVAIL addresses these engineering challenges through **unit-level relational traceability**, **atomic state transitions**, **FEFO allocation with explicit policy guardrails**, **transparent time-series demand forecasting**, and a dedicated **Data Quality Centre**.

---

## 2. Objectives & Intended Users

- **Blood Bank Operations Administrators (Demo):** Monitor eligible unit stock, clear screening queues, process hospital requests via FEFO, control wastage/discards, and configure per-component thresholds.
- **Data & ML Engineers:** Inspect a reproducible 12-month synthetic ETL pipeline (`Extract -> Validate -> Transform -> Load`), PostgreSQL analytical views, and leak-free chronological forecasting evaluation.
- **Technical Reviewers & Recruiters:** Evaluate production-minded full-stack Python architecture, database integrity, automated testing, and restrained healthcare UI design.

---

## 3. Core Features (12 Admin Modules + Patient / User Portal)

1. **Overview Workstation:** 6 database-reconciled summary KPIs, live 8-blood-group available stock strip (`A+` through `O-`), actionable **Needs Attention** alerts with 1-click drill-downs, 4 Plotly operational charts, and filterable recent custody activity.
2. **Unit-Level Inventory Management:** Tracks all 8 ABO/Rh groups and 5 configurable components (`RBC`, `Platelets`, `FFP`, `Whole Blood`, `Cryoprecipitate`) across 9 lifecycle states (`Collected`, `Testing Pending`, `Quarantined`, `Released`, `Reserved`, `Issued`, `Expired`, `Discarded`, `Rejected`). Only cleared, released, non-expired units count as available stock.
3. **Donation Management & Synthetic Donors:** Fictional donor registry, donation intake register, workflow transitions (`Registered -> Collected -> Processing -> Completed/Rejected`), multi-component unit production with traceability, and intake analytics.
4. **Screening & Release Control:** Enforces explicit release actions (`Cleared`, `Quarantined`, `Rejected`). Prevents issuing pending/quarantined/rejected/expired units and permanently blocks rejected units from release.
5. **Hospital Blood Requests:** Full request workflow (`Submitted` -> `Approved` -> `Partially/Fully Allocated` -> `Issued` / `Rejected` / `Cancelled`) with mandatory rejection reasons and over-fulfilment prevention.
6. **FEFO Inventory Allocation Engine:** Ranks eligible released units strictly by earliest expiry date, presents a dry-run **Allocation Preview**, enforces an explicit human-approval warning (pluggable `CompatibilityPolicy` interface—never hardcoding unverified clinical cross-match matrices), reserves units atomically, and supports clean allocation reversal rollbacks.
7. **Regional Network, Surgery Booking & Cold-Chain Dispatch:** 4 geo-located blood storage hubs, Haversine nearest-hub live stock finder & proximity map, advance surgical pre-reservation (enforcing `unit.expiry_date >= surgery_date`), cold-chain transport dispatch tracking (`Scheduled -> Dispatched -> In Transit -> Delivered`), and itemized cost-recovery billing with ReportLab PDF invoices.
8. **Role-Isolated Patient / User Portal:** Dedicated patient/requester sign-in (`patient` / `patient123`) plus bcrypt self-registration with 5 scoped views: Live Blood Availability, Submit Blood Request, Surgery Pre-Reservation, My Requests & Dispatch, and Processing Fees & PDF Receipts.
9. **Expiry Monitor & Wastage Governance:** Component-specific configurable warning and critical expiry windows, wastage trend analytics, controlled expiry sweep, and audited discard transactions (never silent deletion).
10. **Demand Intelligence:** Multi-dimensional demand filters, monthly trends, fulfilment rate tracking, blood-group demand heatmap, and dynamic **evidence-based observations** (with period, supporting metric, baseline, and data coverage).
11. **Demand Forecasting (7 / 14 / 30 Days) & Shortage Planning:** Compares **Seasonal Naive (Lag-7)**, **Moving Average (7d)**, and **Random Forest Regressor** using strict chronological train/test splits (no random shuffling), uncertainty bands, automatic Moving Average fallback for sparse series, and transparent rules-based shortage risk scoring.
12. **Data Quality Centre, Reports & Settings:** 14 automated operational integrity checks with controlled audit-logged remediation, ETL execution logs, 8 downloadable reports (**CSV, Excel `.xlsx`, ReportLab PDF** — donor PII excluded by default), Power BI SQL views & CSV export pack, and dynamic blood bank/threshold configuration.

---

## 4. Architecture Overview

```mermaid
flowchart LR
    A["Streamlit UI (Horizontal Nav + Plotly)"] --> B["Domain Services (backend/services/)"]
    A --> C["ML Engine (Forecasting + Shortage Rules)"]
    B --> D["Pydantic v2 + State Machine Validators"]
    D --> E["SQLAlchemy 2.0 ORM (20 Tables)"]
    C --> E
    F["ETL Pipeline (Generate -> Validate -> Load)"] --> E
    E --> G[("PostgreSQL / SQLite + 7 SQL Views")]
    G --> H["ReportLab PDF / Excel / CSV / Power BI"]
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for entity relationships and layer responsibilities.

---

## 5. Technology Stack

| Layer | Technologies |
|---|---|
| **Frontend** | Streamlit 1.67, Custom Editorial Healthcare CSS (`Inter`), Plotly 7.1 |
| **Backend & Validation** | Python 3.14 (3.11+ compatible), SQLAlchemy 2.0, Pydantic v2, bcrypt, Alembic |
| **Database** | PostgreSQL (`psycopg[binary]`) + local SQLite fallback with 7 analytical SQL views |
| **Data & Machine Learning** | Pandas, NumPy, Scikit-learn (`RandomForestRegressor`), Joblib |
| **Reporting & BI** | ReportLab (PDF), XlsxWriter / openpyxl (Excel), CSV, Power BI PostgreSQL views |
| **Testing** | Pytest + Streamlit `AppTest` |

---

## 6. Project Structure

```text
90-days-90-projects-day-24-sangvail/
├── app/
│   ├── main.py                      # Streamlit entry point & horizontal workstation router
│   ├── config.py                    # Palette, domain constants, paths, env loader
│   ├── components/                  # navigation.py, charts.py, tables.py, filters.py, forms.py
│   ├── pages/                       # 12 operational/intelligence views + Patient Portal
│   └── styles/theme.css             # Full-screen clinical operations stylesheet
├── backend/
│   ├── database.py                  # PostgreSQL / SQLite engine + 7 analytical views
│   ├── models.py                    # 20 SQLAlchemy 2.0 ORM tables with constraints & indexes
│   ├── schemas.py                   # Pydantic v2 input validation models
│   ├── auth.py                      # bcrypt hashing, patient registration & audit logging
│   ├── repositories/                # Master table lookups
│   ├── services/                    # inventory, donation, screening, request, allocation, network_dispatch, expiry, analytics, data_quality, report, settings
│   └── validators/                  # State machine & issuance/allocation guardrails
├── etl/                             # generate_data.py, extract.py, validate.py, transform.py, load.py
├── ml/                              # demand_forecasting.py, model_evaluation.py, shortage_analysis.py, expiry_analysis.py
├── database/                        # schema.sql, views.sql, seed_data.py
├── migrations/                      # Alembic migration configuration
├── tests/                           # 32 automated pytest unit, integration, ML, report, portal & UI tests
├── docs/                            # ARCHITECTURE, PROJECT_OVERVIEW, USER_GUIDE, DEVELOPMENT_NOTES, TESTING, TROUBLESHOOTING, POWER_BI_GUIDE
├── screenshots/                     # Screenshot capture instructions
├── setup.bat / run.bat / test.bat   # One-click Windows setup, launch, and test scripts
├── run.py                           # Cross-platform Python launcher
├── requirements.txt
├── pyproject.toml
├── .env.example
├── QUICKSTART.md
└── DEMO_SCRIPT.md
```

---

## 7. Database Structure

20 relational tables defined in [backend/models.py](backend/models.py) and mirrored in [database/schema.sql](database/schema.sql):

- **Master:** `blood_groups`, `blood_components`, `blood_banks` (geo-located), `hospitals` (geo-located)
- **Custody & Screening:** `donors`, `donations`, `blood_units`, `screening_records`
- **Fulfilment & Transactions:** `blood_requests`, `blood_allocations`, `inventory_transactions`
- **Network, Surgery & Billing:** `surgical_bookings`, `transport_dispatches`, `service_payments`
- **Intelligence & Governance:** `forecast_results`, `stock_thresholds`, `users`, `audit_logs`, `app_settings`, `etl_run_logs`
- **Analytical Views (`database/views.sql`):** `v_current_inventory`, `v_blood_group_availability`, `v_monthly_demand`, `v_monthly_utilization`, `v_expiry_exposure`, `v_request_fulfilment`, `v_data_quality_issues`

---

## 8. Prerequisites & Step-by-Step Windows Installation

### Prerequisites
- Windows 10/11
- Python 3.11+ (verified on **Python 3.14.7**)
- Optional: PostgreSQL 15+ (not required; SQLite works immediately out of the box)

### Fast Windows Setup (Recommended)

```powershell
cd "D:\90 days\90-days-90-projects-day-24-sangvail"
.\setup.bat
.\run.bat
```

### Manual PowerShell Setup

```powershell
cd "D:\90 days\90-days-90-projects-day-24-sangvail"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python database\seed_data.py
streamlit run app\main.py
```

### Environment Variables (`.env.example`)
Copy `.env.example` to `.env` (never commit `.env`):
- `DATABASE_URL`: Defaults to `sqlite:///data/sangvail.db`. For PostgreSQL, set `postgresql+psycopg://user:password@localhost:5432/sangvail`.
- `DEMO_ADMIN_USERNAME` / `DEMO_ADMIN_PASSWORD`: Local demonstration login only.
- `SYNTHETIC_DATA_SEED`: Fixed seed (`42`) for reproducible synthetic datasets.

---

## 9. Demo Credentials & Synthetic Dataset

- **Local URL:** `http://localhost:8501`
- **Administrator Account:** `admin` / `admin123`
- **Patient / User Portal Account:** `patient` / `patient123` (self-registration also enabled)
  *(Local synthetic demonstration only — change credentials before any shared deployment.)*

### Seeded 12-Month Synthetic Dataset (`SYNTHETIC_DATA_SEED=42`)
- **500** fictional donors
- **1,000** donations across 4 geo-located regional blood storage hubs
- **1,632** traceable individual blood units across 8 blood groups & 5 components
- **1,632** fictional screening records
- **1,200** hospital requests across 6 fictional hospitals
- **895** FEFO-consistent allocation records
- **5,784** chronological inventory transactions
- **14/14** automated Data Quality checks implemented with controlled remediation

---

## 10. ML Methodology & Measured Evaluation Metrics

SANGVAIL uses **strict chronological holdout evaluation** (no random shuffling) with strictly causal lagged and rolling features (`lag_1`, `lag_7`, `lag_14`, `roll_mean_7`, `roll_mean_14`, `roll_std_7`, calendar day-of-week/month/weekend) to prevent temporal leakage.

Measured holdout metrics on the seeded 12-month synthetic dataset (`test_days = 28`, `seed = 42`):

| Demand Slice | History | Seasonal Naive (Lag-7) MAE / RMSE | Moving Average (7d) MAE / RMSE | Random Forest MAE / RMSE | Auto-Selected Model |
|---|---:|---:|---:|---:|---|
| All Groups · All Components | 366d | 3.500 / 4.027 | **2.786 / 3.340** | 2.914 / 3.544 | Moving Average (7d) |
| All Groups · RBC | 366d | 1.500 / 1.964 | **1.362 / 1.633** | 1.630 / 1.856 | Moving Average (7d) |
| O+ · RBC | 365d | 0.750 / 1.210 | 0.857 / 1.135 | **0.921 / 1.120** | Random Forest Regressor |
| A+ · RBC | 359d | 1.143 / 1.732 | 0.944 / 1.254 | **0.952 / 1.147** | Random Forest Regressor |

*Note: Forecast outputs are non-negative statistical planning estimates with uncertainty ranges—not guaranteed future requirements. Sparse series (<35 days) automatically fall back to Moving Average with an explicit limitation notice.*

---

## 11. Screenshots & Demo

Genuine desktop captures (`1440×920`) of the running **SANGVAIL** workstation:

| Workstation View | Screenshot |
|---|---|
| **Editorial Split Sign-In Gate** | ![SANGVAIL Login](screenshots/login-screen.png) |
| **Operations Overview & Needs Attention** | ![SANGVAIL Overview](screenshots/overview-workstation.png) |
| **Unit-Level Blood Custody Ledger** | ![SANGVAIL Inventory](screenshots/inventory-custody.png) |
| **Hospital Requests & FEFO Allocation** | ![SANGVAIL Requests](screenshots/requests-fefo.png) |
| **Demand Forecasting & Chronological Metrics** | ![SANGVAIL Forecasting](screenshots/forecasting-shortage.png) |
| **14-Check Data Quality Centre** | ![SANGVAIL Data Quality](screenshots/data-quality-centre.png) |

Follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for a structured 60–120 second portfolio walkthrough.

---

## 12. Testing Instructions & Verified Status

Run the automated test suite:

```powershell
.\test.bat
# or
.\.venv\Scripts\python.exe -m pytest -v
```

**Verified Test Status:** **PASS** — `32 passed in 45.53s` (0 failures, 0 warnings), covering inventory integrity, donations, screening controls, hospital requests, FEFO allocation & rollback, regional hubs/surgery holds/transport/PDF receipts, patient portal registration & isolation, component-specific expiry windows, chronological ML evaluation, 14-check Data Quality detection & remediation, CSV/Excel/PDF report exports, and Streamlit `AppTest` navigation. See [docs/TESTING.md](docs/TESTING.md).

---

## 13. Known Limitations & Security Considerations

- **Educational Synthetic Scope:** Not certified for clinical blood banking, medical decision-making, or HIPAA/regulatory compliance.
- **No Hardcoded Clinical Cross-Match Matrix:** Allocation defaults to an explicit `AdministrativeExactMatchPolicy` requiring human approval acknowledgement; real clinical compatibility requires integrating an institutionally validated policy engine.
- **Authentication:** Local single-admin bcrypt login is intended for single-machine demonstration; multi-user RBAC, session timeouts, TLS, and secret rotation are required before multi-user deployment.
- **Donor Privacy:** Report exports exclude donor names and contact fields by default.

---

## 14. Future Enhancements

- Role-based access control (Lab Technician, Inventory Officer, Hospital Coordinator, QA Auditor).
- Integration adapters for institutional HL7/FHIR and validated LIS screening feeds.
- Cold-chain IoT temperature excursion ingestion with automatic quarantine triggers.
- Probabilistic quantile forecasting (e.g., Gradient Boosting quantiles / Prophet) for peak trauma surges.

---



## 15. License

Released under the [MIT License](LICENSE).
