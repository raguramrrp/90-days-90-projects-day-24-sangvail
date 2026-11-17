# SANGVAIL Quick Start Guide (Windows)

## Option 1 — One-Click Batch Scripts (Recommended)

```powershell
cd "D:\90 days\90-days-90-projects-day-24-sangvail"
.\setup.bat
.\run.bat
```

To run the automated test suite:

```powershell
.\test.bat
```

## Option 2 — Manual PowerShell Setup

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

Or simply launch with the Python entry point:

```powershell
python run.py
```

## Local Access & Demo Credentials

- **URL:** `http://localhost:8501`
- **Username:** `admin`
- **Password:** `admin123`

> **Security & Safety Notice:** Default credentials are for local synthetic-data demonstration only. Change credentials before any shared deployment. All operational records are synthetically generated.

## Optional PostgreSQL Configuration

SANGVAIL uses SQLite (`data/sangvail.db`) out of the box so it runs immediately without external services. To switch to PostgreSQL:

1. Create a database (e.g., `createdb sangvail`).
2. Edit `.env` and set:
   ```dotenv
   DATABASE_URL=postgresql+psycopg://sangvail_user:YOUR_PASSWORD@localhost:5432/sangvail
   ```
3. Run `python database\seed_data.py` to create all 17 tables, 7 analytical views, and seed the 12-month synthetic dataset.
