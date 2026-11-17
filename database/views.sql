-- SANGVAIL PostgreSQL Analytical & Power BI Views

CREATE OR REPLACE VIEW v_current_inventory AS
SELECT
    bu.id AS unit_id,
    bu.unit_reference,
    bb.bank_name,
    bg.display_name AS blood_group,
    bc.component_name,
    bu.collection_date,
    bu.processing_date,
    bu.expiry_date,
    (bu.expiry_date - CURRENT_DATE) AS remaining_days,
    bu.screening_status,
    bu.inventory_status,
    bu.storage_location
FROM blood_units bu
JOIN blood_banks bb ON bb.id = bu.blood_bank_id
JOIN blood_groups bg ON bg.id = bu.blood_group_id
JOIN blood_components bc ON bc.id = bu.component_id;

CREATE OR REPLACE VIEW v_blood_group_availability AS
SELECT
    bb.id AS blood_bank_id,
    bb.bank_name,
    bg.display_name AS blood_group,
    bc.component_name,
    COUNT(bu.id) AS total_units,
    SUM(CASE WHEN bu.inventory_status = 'Released' AND bu.expiry_date >= CURRENT_DATE THEN 1 ELSE 0 END) AS available_units,
    SUM(CASE WHEN bu.inventory_status = 'Reserved' THEN 1 ELSE 0 END) AS reserved_units,
    SUM(CASE WHEN bu.inventory_status IN ('Collected', 'Testing Pending') THEN 1 ELSE 0 END) AS pending_screening_units,
    SUM(CASE WHEN bu.inventory_status = 'Quarantined' THEN 1 ELSE 0 END) AS quarantined_units,
    SUM(CASE WHEN bu.inventory_status = 'Issued' THEN 1 ELSE 0 END) AS issued_units,
    SUM(CASE WHEN bu.inventory_status = 'Expired' OR (bu.inventory_status = 'Released' AND bu.expiry_date < CURRENT_DATE) THEN 1 ELSE 0 END) AS expired_units,
    SUM(CASE WHEN bu.inventory_status = 'Discarded' THEN 1 ELSE 0 END) AS discarded_units
FROM blood_units bu
JOIN blood_banks bb ON bb.id = bu.blood_bank_id
JOIN blood_groups bg ON bg.id = bu.blood_group_id
JOIN blood_components bc ON bc.id = bu.component_id
GROUP BY bb.id, bb.bank_name, bg.display_name, bc.component_name;

CREATE OR REPLACE VIEW v_monthly_demand AS
SELECT
    to_char(br.request_date, 'YYYY-MM') AS demand_month,
    bg.display_name AS blood_group,
    bc.component_name,
    COUNT(br.id) AS request_count,
    SUM(br.required_quantity) AS total_requested_units,
    SUM(br.fulfilled_quantity) AS total_fulfilled_units,
    SUM(br.required_quantity - br.fulfilled_quantity) AS unfulfilled_units
FROM blood_requests br
JOIN blood_groups bg ON bg.id = br.blood_group_id
JOIN blood_components bc ON bc.id = br.component_id
WHERE br.status NOT IN ('Cancelled', 'Rejected')
GROUP BY to_char(br.request_date, 'YYYY-MM'), bg.display_name, bc.component_name;

CREATE OR REPLACE VIEW v_monthly_utilization AS
SELECT
    to_char(it.created_at, 'YYYY-MM') AS activity_month,
    bg.display_name AS blood_group,
    bc.component_name,
    SUM(CASE WHEN it.transaction_type = 'COLLECTED' THEN it.quantity ELSE 0 END) AS collected_units,
    SUM(CASE WHEN it.transaction_type = 'RELEASED' THEN it.quantity ELSE 0 END) AS released_units,
    SUM(CASE WHEN it.transaction_type = 'ISSUED' THEN it.quantity ELSE 0 END) AS issued_units,
    SUM(CASE WHEN it.transaction_type IN ('EXPIRED', 'DISCARDED') THEN it.quantity ELSE 0 END) AS wastage_units
FROM inventory_transactions it
JOIN blood_units bu ON bu.id = it.unit_id
JOIN blood_groups bg ON bg.id = bu.blood_group_id
JOIN blood_components bc ON bc.id = bu.component_id
GROUP BY to_char(it.created_at, 'YYYY-MM'), bg.display_name, bc.component_name;

CREATE OR REPLACE VIEW v_expiry_exposure AS
SELECT
    bu.id AS unit_id,
    bu.unit_reference,
    bb.bank_name,
    bg.display_name AS blood_group,
    bc.component_name,
    bu.collection_date,
    bu.expiry_date,
    (bu.expiry_date - CURRENT_DATE) AS remaining_days,
    bu.inventory_status,
    bu.storage_location
FROM blood_units bu
JOIN blood_banks bb ON bb.id = bu.blood_bank_id
JOIN blood_groups bg ON bg.id = bu.blood_group_id
JOIN blood_components bc ON bc.id = bu.component_id
WHERE bu.inventory_status IN ('Released', 'Reserved', 'Expired', 'Testing Pending', 'Quarantined');

CREATE OR REPLACE VIEW v_request_fulfilment AS
SELECT
    br.id AS request_id,
    br.request_reference,
    h.hospital_name,
    bg.display_name AS blood_group,
    bc.component_name,
    br.urgency,
    br.request_date,
    br.required_date,
    br.required_quantity,
    br.fulfilled_quantity,
    (br.required_quantity - br.fulfilled_quantity) AS remaining_quantity,
    br.status
FROM blood_requests br
JOIN hospitals h ON h.id = br.hospital_id
JOIN blood_groups bg ON bg.id = br.blood_group_id
JOIN blood_components bc ON bc.id = br.component_id;

CREATE OR REPLACE VIEW v_data_quality_issues AS
SELECT
    'EXPIRED_MARKED_RELEASED' AS issue_code,
    'Critical' AS severity,
    'blood_unit' AS entity_type,
    bu.unit_reference AS entity_reference,
    'Unit is past expiry date but still marked Released' AS description
FROM blood_units bu
WHERE bu.inventory_status = 'Released' AND bu.expiry_date < CURRENT_DATE
UNION ALL
SELECT
    'INVALID_PROCESSING_DATE' AS issue_code,
    'Critical' AS severity,
    'blood_unit' AS entity_type,
    bu.unit_reference AS entity_reference,
    'Processing date precedes collection date' AS description
FROM blood_units bu
WHERE bu.processing_date IS NOT NULL AND bu.processing_date < bu.collection_date
UNION ALL
SELECT
    'INVALID_EXPIRY_DATE' AS issue_code,
    'Critical' AS severity,
    'blood_unit' AS entity_type,
    bu.unit_reference AS entity_reference,
    'Expiry date is on or before collection date' AS description
FROM blood_units bu
WHERE bu.expiry_date <= bu.collection_date
UNION ALL
SELECT
    'OVER_ALLOCATED_REQUEST' AS issue_code,
    'Critical' AS severity,
    'blood_request' AS entity_type,
    br.request_reference AS entity_reference,
    'Fulfilled quantity exceeds required quantity' AS description
FROM blood_requests br
WHERE br.fulfilled_quantity > br.required_quantity;
