"""Automated tests for Module 7 — Expiry Monitoring & Controlled Discard Governance."""

from __future__ import annotations

from sqlalchemy import select

from backend.models import BloodUnit, InventoryTransaction
from backend.schemas import ThresholdUpdate
from backend.services.expiry_service import (
    get_expiry_monitor_df,
    record_discard_transaction,
    sweep_expired_units,
)
from backend.services.settings_service import upsert_stock_threshold
from tests.conftest import make_demo_donation, make_demo_unit


def test_component_specific_warning_windows_and_expiry_sweep(db_session):
    session, refs, _ = db_session
    bank_id = next(iter(refs["blood_banks"].values()))
    bg_id = refs["blood_groups"]["O+"]
    plt_id = refs["components"]["Platelets"]
    rbc_id = refs["components"]["Red Blood Cells (RBC)"]

    # Configure different thresholds for Platelets vs RBC
    upsert_stock_threshold(
        session,
        ThresholdUpdate(
            blood_bank_id=bank_id,
            blood_group_id=bg_id,
            component_id=plt_id,
            minimum_stock=4,
            warning_days=2,
            critical_days=1,
        ),
    )
    upsert_stock_threshold(
        session,
        ThresholdUpdate(
            blood_bank_id=bank_id,
            blood_group_id=bg_id,
            component_id=rbc_id,
            minimum_stock=8,
            warning_days=10,
            critical_days=4,
        ),
    )
    session.flush()

    don = make_demo_donation(session, bank_id, "50", "O+", days_ago=20)
    make_demo_unit(session, bank_id, don.donation_reference, "SV-PLT-CRIT", "O+", "Platelets", expires_in_days=1)
    make_demo_unit(session, bank_id, don.donation_reference, "SV-RBC-WARN", "O+", "Red Blood Cells (RBC)", expires_in_days=8)
    u_exp = make_demo_unit(session, bank_id, don.donation_reference, "SV-RBC-PAST", "O+", "Red Blood Cells (RBC)", expires_in_days=-3)

    exp_df = get_expiry_monitor_df(session, blood_bank_id=bank_id)
    cat_map = dict(zip(exp_df["unit_reference"], exp_df["expiry_category"]))
    assert cat_map["SV-PLT-CRIT"] == "Critical Window"
    assert cat_map["SV-RBC-WARN"] == "Approaching Expiry"
    assert cat_map["SV-RBC-PAST"] == "Expired"

    # Sweep must move past-expiry Released unit to Expired with transaction log
    moved = sweep_expired_units(session, blood_bank_id=bank_id, actor="pytest")
    assert moved == ["SV-RBC-PAST"]
    assert u_exp.inventory_status == "Expired"

    # Audited discard must keep the unit row (never silently delete) and record DISCARDED transaction
    record_discard_transaction(session, u_exp.id, "Expired while unused", actor="pytest")
    session.flush()
    persisted = session.get(BloodUnit, u_exp.id)
    assert persisted is not None
    assert persisted.inventory_status == "Discarded"
    disc_tx = session.scalar(
        select(InventoryTransaction).where(
            InventoryTransaction.unit_id == u_exp.id,
            InventoryTransaction.transaction_type == "DISCARDED",
        )
    )
    assert disc_tx is not None
    assert "Expired while unused" in disc_tx.reason
