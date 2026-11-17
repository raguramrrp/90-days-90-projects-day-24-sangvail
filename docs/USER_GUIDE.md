# SANGVAIL — User Guide

## Sign In

Open `http://localhost:8501` and sign in using the local demonstration credentials (`admin` / `admin123`) or click **Sign In as Demo Admin**.

## Navigation Structure

SANGVAIL uses a **horizontal primary navigation bar** at the top of the workspace:

- **Overview:** Executive operational KPIs, actionable **Needs Attention** alerts with 1-click drill-downs, 4 Plotly operational charts, and filterable recent inventory transactions.
- **Inventory:** Searchable unit-level custody ledger, reconciled blood-group x component Stock Matrix, and validated unit registration form. Sub-navigation links directly to **Screening & Release**.
- **Donations:** Synthetic donor registry, donation intake register, donation analytics, status progression (`Registered -> Collected -> Processing -> Completed/Rejected`), and multi-component unit production.
- **Screening & Release:** Pending screening queue with SLA tracking, fictional disposition controls (`Cleared (Demo)`, `Quarantined (Demo)`, `Rejected (Demo)`), and full screening audit log.
- **Requests:** Hospital request queue, new request form, request approval/rejection/cancellation, **FEFO Allocation Preview & Confirmation** (with explicit human-approval acknowledgement), allocation reversal, and handover issuance.
- **Expiry:** Component-specific expiry watchlist (`Expired`, `Critical Window`, `Approaching Expiry`, `Normal Shelf Life`), wastage intelligence charts, controlled expiry sweep, and audited discard logging.
- **Intelligence:** Demand Intelligence workspace with date/group/component/hospital/urgency filters, charts, demand heatmap, and dynamic evidence-based operational observations. Sub-navigation links to **Forecasting & Shortage** and **Data Quality Centre**.
- **Forecasting & Shortage:** 7/14/30-day demand forecasting comparing Seasonal Naive, Moving Average, and Random Forest Regressor under chronological evaluation, plus the rules-based Shortage Planning table with plain-English alert explanations.
- **Data Quality:** 14-check automated operational integrity suite, quality score, row-level exception inspection, controlled audit-logged remediation buttons, and ETL execution history.
- **Reports:** Generate and download all 8 operational reports in CSV, Excel (`.xlsx`), and formatted ReportLab PDF, or export the Power BI CSV bundle.
- **Settings:** Configure stock thresholds and expiry windows per blood group and component, edit component shelf-life policies, blood bank profiles, storage locations, application preferences, and inspect the audit log.
