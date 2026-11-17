# SANGVAIL — Troubleshooting Guide

## Common Issues & Fixes

### 1. `Python was not found` when running `setup.bat`
- Install Python 3.11+ (tested on Python 3.14.7) from https://www.python.org/downloads/ and check **Add Python to PATH**.
- Re-open your terminal and run `.\setup.bat`.

### 2. `ModuleNotFoundError: No module named 'backend'`
- Ensure commands are executed from the project root (`D:\90 days\90-days-90-projects-day-24-sangvail`) using the project virtual environment:
  ```powershell
  .\.venv\Scripts\python.exe -m pytest -v
  ```

### 3. Port `8501` is already in use
- Launch Streamlit on an alternate port:
  ```powershell
  .\.venv\Scripts\python.exe -m streamlit run app\main.py --server.port=8502
  ```

### 4. PostgreSQL connection errors (`OperationalError`)
- Verify PostgreSQL is running and credentials in `.env` are correct.
- Ensure the target database exists (`createdb sangvail`).
- To revert to the zero-configuration local SQLite fallback, set `DATABASE_URL=sqlite:///data/sangvail.db` in `.env`.

### 5. Forecast page shows "Moving Average baseline applied"
- Chronological train/test evaluation requires at least 35 days of daily demand observations for the selected blood group + component slice. Select `All` blood groups or a higher-volume component (e.g., RBC) to evaluate Random Forest vs. Seasonal Naive vs. Moving Average.
