# SANGVAIL — Project Overview

## Problem Statement

Blood bank operations rely on strict unit-level custody, screening clearance before release, component-specific cold-chain shelf lives (5 days for Platelets vs. 42 days for RBCs vs. 365 days for FFP), and timely hospital request fulfilment. When inventory is tracked only through aggregate totals or static spreadsheets, facilities risk counting unreleased, quarantined, reserved, or expired units as available stock, leading to avoidable wastage and last-minute shortages.

## Objectives

SANGVAIL (Blood Bank Inventory, Operations & Demand Intelligence Platform) provides a centralized operational workstation that:

1. Maintains **unit-level traceability** from synthetic donor -> donation -> separated component unit -> screening clearance -> FEFO reservation -> hospital issue or audited discard.
2. Enforces **strict state-machine and database integrity** so unavailable stock never leaks into eligible available inventory.
3. Supports **First Expiry, First Out (FEFO)** allocation with dry-run previews, atomic transactions, reversal rollbacks, and an explicit non-clinical compatibility policy integration point.
4. Delivers **transparent demand intelligence, chronological time-series forecasting, and rules-based shortage planning** without black-box claims.
5. Embeds a **Data Quality Centre** that audits 14 operational integrity rules and provides controlled, audit-logged remediation workflows.

## Intended Users

- Blood bank operations managers and inventory coordinators (demonstration context).
- Healthcare data engineers and analysts evaluating relational inventory design, ETL validation, and time-series forecasting.
- Portfolio reviewers and technical interviewers evaluating end-to-end full-stack Python & ML engineering.

## MVP Scope Boundaries & Healthcare Safety Notice

- **Included:** Unit-level inventory management, donation & synthetic donor registry, screening & controlled release workflow, hospital request lifecycle, FEFO allocation engine, expiry & wastage governance, demand intelligence, chronological forecasting (Naive / Moving Average / Random Forest), rules-based shortage planning, 14-check Data Quality Centre, CSV/Excel/PDF reporting, Power BI SQL views & CSV export pack, and configurable settings.
- **Explicitly Excluded:** Real hospital HL7/FHIR integration, real patient or donor PII, automated laboratory diagnostic interpretation, and clinical transfusion cross-matching rules.
