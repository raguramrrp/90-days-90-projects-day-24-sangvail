# SANGVAIL — Development Notes & Engineering Decisions

## Key Design Decisions

1. **Unit-Level Custody Over Aggregate Balances**
   - Available inventory is never calculated as `sum(donations) - sum(requests)`. Every blood unit is an individual database row with its own collection date, processing date, component-specific expiry date, screening status, and inventory status.
   - Only rows where `inventory_status == 'Released'` and `expiry_date >= today` count toward eligible available stock.

2. **Pluggable Compatibility Policy Integration Point**
   - Rather than hardcoding an unverified clinical ABO/Rh cross-match matrix, `backend/services/allocation_service.py` defines a `CompatibilityPolicy` protocol.
   - The default implementation (`AdministrativeExactMatchPolicy`) matches exact blood-group label and component ID solely for demonstration, marks `is_clinically_validated = False`, displays a prominent advisory banner, and enforces explicit human confirmation before reserving inventory.

3. **Strict Chronological Time-Series Validation**
   - Random K-fold or random train/test splits cause severe temporal leakage in demand forecasting. `ml/model_evaluation.py` evaluates Seasonal Naive (Lag-7), Moving Average (7d), and Random Forest Regressor on a strict chronological holdout tail using strictly causal lagged and rolling features (`shift(1)` prior to rolling windows).
   - Sparse series (< 35 daily observations) automatically fall back to Moving Average with an explicit limitation notice.

4. **PostgreSQL Primary Design with Zero-Friction SQLite Fallback**
   - SQLAlchemy 2.0 ORM models, Alembic migrations, `database/schema.sql`, and `database/views.sql` support PostgreSQL natively via `psycopg[binary]`.
   - When `DATABASE_URL` is omitted or defaults to `sqlite:///data/sangvail.db`, SQLite runs with `PRAGMA foreign_keys=ON` and WAL mode, creating dialect-compatible versions of all 7 analytical views automatically.

5. **Restrained Editorial Healthcare UI**
   - Deliberately avoids stereotypical AI dashboard clichés (dark neon themes, purple gradients, cluttered KPI walls, permanent left sidebars). Uses a horizontal top workstation bar, `#F5F6F4` canvas, `#315F52` deep forest accent, and reserves `#B94C4C` strictly for genuine critical alerts.
