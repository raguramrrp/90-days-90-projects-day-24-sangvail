# SANGVAIL — 90-Second Portfolio Demo Script

**Target Duration:** 60–120 seconds  
**Local URL:** `http://localhost:8501`  
**Demo Login:** `admin` / `admin123`

## Sequence

1. **Sign-In & Workstation Design (0:00–0:15)**
   - Open `http://localhost:8501`. Point out the restrained healthcare-operations visual identity, `DEMO DATA` badge, bcrypt-backed login, and security notice.
   - Click **Sign In as Demo Admin**.

2. **Decision-Oriented Overview (0:15–0:30)**
   - Highlight the horizontal primary navigation bar (no cluttered left sidebar), blood bank switcher, and 6 reconciled summary metrics derived directly from individual `blood_units`.
   - Show the **Needs Attention** actionable alerts (low stock below configured floor, critical expiry window, overdue screening SLA, urgent open requests) and click **Inspect ->** to jump straight into context.

3. **Unit-Level Inventory & Screening Control (0:30–0:50)**
   - Open **Inventory** -> show unit-level custody ledger (1,632 seeded units), filters, and reconciled Stock Matrix proving reserved/pending/expired units never count as available stock.
   - Switch to **Screening & Release** -> select a pending unit, apply **Release to Eligible Inventory (Cleared - Demo)**, and show the immediate transaction & audit trail.

4. **Blood Requests & FEFO Allocation Engine (0:50–1:15)**
   - Open **Requests** -> **Manage & FEFO Allocate**.
   - Select an approved open request to view the **FEFO Allocation Preview** sorted strictly by earliest expiry date, complete with the non-clinical administrative policy warning and explicit human-approval checkbox.
   - Confirm allocation, then show **Confirm Authorized Handover (Mark Issued)** or **Reverse Reservation** restoring unit availability atomically.

5. **Expiry Governance, Demand Intelligence & Forecasting (1:15–1:40)**
   - Open **Expiry** -> show component-specific expiry windows (Platelets vs. RBC vs. FFP) and audited discard logging.
   - Open **Intelligence** -> show evidence-based dynamic observations (period, metric, baseline, data coverage) and demand heatmap.
   - Open **Forecasting & Shortage** -> compare Seasonal Naive, Moving Average, and Random Forest Regressor metrics (strict chronological holdout split, no shuffling) and inspect the explainable **Shortage Planning Intelligence** reasons.

6. **Data Quality Centre & Reports (1:40–2:00)**
   - Open **Data Quality** -> show the 14-check operational integrity matrix (100% clean score on seeded dataset) and ETL execution report (`12,855` records extracted & validated).
   - Open **Reports** -> download a formatted ReportLab PDF report or export the Power BI CSV bundle.
