# SANGVAIL — Power BI Optional Integration Guide

SANGVAIL operates completely standalone in Streamlit without requiring Power BI Desktop. When optional executive BI dashboards are desired, connect Power BI using either **PostgreSQL Views** or **CSV Snapshots**.

## Option A: Direct PostgreSQL Connection

1. Configure `DATABASE_URL=postgresql+psycopg://...` in `.env` and run `python database\seed_data.py`.
2. In Power BI Desktop, choose **Get Data -> PostgreSQL database**.
3. Connect to `localhost:5432` and database `sangvail`.
4. Select the pre-built analytical views from `database/views.sql`:
   - `v_current_inventory`
   - `v_blood_group_availability`
   - `v_monthly_demand`
   - `v_monthly_utilization`
   - `v_expiry_exposure`
   - `v_request_fulfilment`
   - `v_data_quality_issues`

## Option B: CSV Snapshot Bundle (No PostgreSQL Required)

1. Open SANGVAIL -> **Reports** -> **Power BI Analytical Layer**.
2. Click **Export All Power BI CSV Snapshots to exports/**.
3. Load `exports/pbi_*.csv` into Power BI Desktop via **Get Data -> Folder** or **Text/CSV**.

## Suggested Power BI Report Pages

1. **Executive Overview** (`v_blood_group_availability`, `v_monthly_utilization`)
2. **Blood Inventory** (`v_current_inventory`)
3. **Collection & Utilization** (`v_monthly_utilization`)
4. **Request Fulfilment** (`v_request_fulfilment`, `v_monthly_demand`)
5. **Expiry & Wastage** (`v_expiry_exposure`, `pbi_expiry_wastage.csv`)
6. **Demand Forecasting** (`forecast_results`, `pbi_demand_forecasting.csv`)
