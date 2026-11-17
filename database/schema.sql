-- SANGVAIL PostgreSQL Reference Schema
-- Blood Bank Inventory, Operations & Demand Intelligence Platform
-- Mirrors backend/models.py (SQLAlchemy 2.0 ORM)

CREATE TABLE IF NOT EXISTS blood_groups (
    id SERIAL PRIMARY KEY,
    abo_group VARCHAR(4) NOT NULL,
    rh_factor VARCHAR(2) NOT NULL,
    display_name VARCHAR(8) NOT NULL UNIQUE,
    CONSTRAINT uq_blood_group_abo_rh UNIQUE (abo_group, rh_factor)
);

CREATE TABLE IF NOT EXISTS blood_components (
    id SERIAL PRIMARY KEY,
    component_name VARCHAR(80) NOT NULL UNIQUE,
    short_code VARCHAR(16) NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    default_shelf_life_days INTEGER NOT NULL DEFAULT 42 CHECK (default_shelf_life_days > 0),
    storage_temp_range VARCHAR(64) NOT NULL DEFAULT '2°C to 6°C',
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS blood_banks (
    id SERIAL PRIMARY KEY,
    bank_name VARCHAR(140) NOT NULL UNIQUE,
    address VARCHAR(255) NOT NULL,
    contact VARCHAR(120) NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    status VARCHAR(32) NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS hospitals (
    id SERIAL PRIMARY KEY,
    hospital_name VARCHAR(160) NOT NULL UNIQUE,
    address VARCHAR(255) NOT NULL,
    contact VARCHAR(120) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS donors (
    id SERIAL PRIMARY KEY,
    donor_reference VARCHAR(40) NOT NULL UNIQUE,
    full_name VARCHAR(120) NOT NULL,
    age_band VARCHAR(24) NOT NULL,
    blood_group_id INTEGER NOT NULL REFERENCES blood_groups(id),
    contact VARCHAR(120) NOT NULL,
    registration_date DATE NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'Active'
);

CREATE TABLE IF NOT EXISTS donations (
    id SERIAL PRIMARY KEY,
    donation_reference VARCHAR(40) NOT NULL UNIQUE,
    donor_id INTEGER NOT NULL REFERENCES donors(id),
    blood_bank_id INTEGER NOT NULL REFERENCES blood_banks(id),
    donation_date DATE NOT NULL,
    collection_location VARCHAR(140) NOT NULL,
    collection_type VARCHAR(64) NOT NULL,
    collection_status VARCHAR(32) NOT NULL,
    collected_quantity INTEGER NOT NULL CHECK (collected_quantity > 0),
    collection_staff VARCHAR(100) NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_by VARCHAR(80) NOT NULL DEFAULT 'admin'
);

CREATE TABLE IF NOT EXISTS blood_units (
    id SERIAL PRIMARY KEY,
    unit_reference VARCHAR(40) NOT NULL UNIQUE,
    donation_id INTEGER NOT NULL REFERENCES donations(id),
    blood_bank_id INTEGER NOT NULL REFERENCES blood_banks(id),
    blood_group_id INTEGER NOT NULL REFERENCES blood_groups(id),
    component_id INTEGER NOT NULL REFERENCES blood_components(id),
    collection_date DATE NOT NULL,
    processing_date DATE,
    expiry_date DATE NOT NULL,
    screening_status VARCHAR(40) NOT NULL DEFAULT 'Pending',
    inventory_status VARCHAR(40) NOT NULL DEFAULT 'Testing Pending',
    storage_location VARCHAR(120) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_units_status_group_comp_expiry
    ON blood_units (inventory_status, blood_group_id, component_id, expiry_date);

CREATE TABLE IF NOT EXISTS screening_records (
    id SERIAL PRIMARY KEY,
    screening_reference VARCHAR(40) NOT NULL UNIQUE,
    unit_id INTEGER NOT NULL REFERENCES blood_units(id),
    screening_status VARCHAR(40) NOT NULL,
    screening_date DATE NOT NULL,
    result_reference VARCHAR(80) NOT NULL DEFAULT 'DEMO-REF',
    reviewed_by VARCHAR(80),
    reviewed_at TIMESTAMP,
    reference_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS blood_requests (
    id SERIAL PRIMARY KEY,
    request_reference VARCHAR(40) NOT NULL UNIQUE,
    blood_bank_id INTEGER NOT NULL REFERENCES blood_banks(id),
    hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
    blood_group_id INTEGER NOT NULL REFERENCES blood_groups(id),
    component_id INTEGER NOT NULL REFERENCES blood_components(id),
    required_quantity INTEGER NOT NULL CHECK (required_quantity > 0),
    fulfilled_quantity INTEGER NOT NULL DEFAULT 0 CHECK (fulfilled_quantity >= 0),
    urgency VARCHAR(32) NOT NULL DEFAULT 'Routine',
    request_date DATE NOT NULL,
    required_date DATE NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'Submitted',
    notes TEXT NOT NULL DEFAULT '',
    created_by VARCHAR(80) NOT NULL DEFAULT 'admin'
);

CREATE TABLE IF NOT EXISTS blood_allocations (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES blood_requests(id),
    unit_id INTEGER NOT NULL REFERENCES blood_units(id),
    allocation_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    allocated_by VARCHAR(80) NOT NULL,
    allocation_status VARCHAR(32) NOT NULL DEFAULT 'Reserved',
    issue_date TIMESTAMP,
    policy_acknowledged BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id SERIAL PRIMARY KEY,
    unit_id INTEGER NOT NULL REFERENCES blood_units(id),
    transaction_type VARCHAR(40) NOT NULL,
    previous_status VARCHAR(40),
    new_status VARCHAR(40) NOT NULL,
    reference_type VARCHAR(40) NOT NULL DEFAULT 'UNIT',
    reference_id VARCHAR(64) NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    reason TEXT NOT NULL DEFAULT '',
    performed_by VARCHAR(80) NOT NULL DEFAULT 'admin',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS forecast_results (
    id SERIAL PRIMARY KEY,
    blood_group_id INTEGER NOT NULL REFERENCES blood_groups(id),
    component_id INTEGER NOT NULL REFERENCES blood_components(id),
    forecast_date DATE NOT NULL,
    predicted_demand DOUBLE PRECISION NOT NULL,
    lower_bound DOUBLE PRECISION NOT NULL,
    upper_bound DOUBLE PRECISION NOT NULL,
    model_name VARCHAR(64) NOT NULL,
    mae DOUBLE PRECISION,
    rmse DOUBLE PRECISION,
    generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_thresholds (
    id SERIAL PRIMARY KEY,
    blood_bank_id INTEGER NOT NULL REFERENCES blood_banks(id),
    blood_group_id INTEGER NOT NULL REFERENCES blood_groups(id),
    component_id INTEGER NOT NULL REFERENCES blood_components(id),
    minimum_stock INTEGER NOT NULL DEFAULT 5 CHECK (minimum_stock >= 0),
    warning_days INTEGER NOT NULL DEFAULT 7,
    critical_days INTEGER NOT NULL DEFAULT 3 CHECK (critical_days >= 1),
    CONSTRAINT uq_threshold_bank_group_comp UNIQUE (blood_bank_id, blood_group_id, component_id),
    CONSTRAINT ck_threshold_warning_ge_critical CHECK (warning_days >= critical_days)
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    role VARCHAR(40) NOT NULL DEFAULT 'Administrator',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    actor_name VARCHAR(80) NOT NULL DEFAULT 'system',
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(60) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(80) NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS etl_run_logs (
    id SERIAL PRIMARY KEY,
    run_reference VARCHAR(48) NOT NULL UNIQUE,
    source_name VARCHAR(160) NOT NULL,
    records_extracted INTEGER NOT NULL DEFAULT 0,
    records_accepted INTEGER NOT NULL DEFAULT 0,
    records_rejected INTEGER NOT NULL DEFAULT 0,
    duplicate_records INTEGER NOT NULL DEFAULT 0,
    validation_summary TEXT NOT NULL DEFAULT '',
    execution_seconds DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status VARCHAR(32) NOT NULL DEFAULT 'Completed',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
