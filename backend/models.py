"""SQLAlchemy ORM models for SANGVAIL."""

from __future__ import annotations

from datetime import date, datetime, timezone
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Master Tables
# ---------------------------------------------------------------------------


class BloodGroup(Base):
    __tablename__ = "blood_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abo_group: Mapped[str] = mapped_column(String(4), nullable=False)
    rh_factor: Mapped[str] = mapped_column(String(2), nullable=False)
    display_name: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)

    __table_args__ = (
        UniqueConstraint("abo_group", "rh_factor", name="uq_blood_group_abo_rh"),
    )


class BloodComponent(Base):
    __tablename__ = "blood_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    short_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_shelf_life_days: Mapped[int] = mapped_column(Integer, nullable=False, default=42)
    storage_temp_range: Mapped[str] = mapped_column(String(64), nullable=False, default="2°C to 6°C")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("default_shelf_life_days > 0", name="ck_component_shelf_life_positive"),
    )


class BloodBank(Base):
    __tablename__ = "blood_banks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_name: Mapped[str] = mapped_column(String(140), nullable=False, unique=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    contact: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    latitude: Mapped[float] = mapped_column(Float, nullable=False, default=13.0827)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, default=80.2707)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Active")


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    contact: Mapped[str] = mapped_column(String(120), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False, default=13.0604)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, default=80.2496)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Active")


# ---------------------------------------------------------------------------
# Donor, Donation & Unit Tables
# ---------------------------------------------------------------------------


class Donor(Base):
    __tablename__ = "donors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    donor_reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    age_band: Mapped[str] = mapped_column(String(24), nullable=False)
    blood_group_id: Mapped[int] = mapped_column(ForeignKey("blood_groups.id"), nullable=False, index=True)
    contact: Mapped[str] = mapped_column(String(120), nullable=False)
    registration_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Active")

    blood_group: Mapped["BloodGroup"] = relationship()


class Donation(Base):
    __tablename__ = "donations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    donation_reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id"), nullable=False, index=True)
    blood_bank_id: Mapped[int] = mapped_column(ForeignKey("blood_banks.id"), nullable=False, index=True)
    donation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    collection_location: Mapped[str] = mapped_column(String(140), nullable=False, default="Main Donor Suite")
    collection_type: Mapped[str] = mapped_column(String(64), nullable=False, default="Whole Blood Collection")
    collection_status: Mapped[str] = mapped_column(String(32), nullable=False, default="Collected")
    collected_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=450)
    collection_staff: Mapped[str] = mapped_column(String(100), nullable=False, default="Collection Technician")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")

    donor: Mapped["Donor"] = relationship()
    blood_bank: Mapped["BloodBank"] = relationship()
    units: Mapped[list["BloodUnit"]] = relationship(back_populates="donation")

    __table_args__ = (
        CheckConstraint("collected_quantity > 0", name="ck_donation_quantity_positive"),
    )


class BloodUnit(Base):
    __tablename__ = "blood_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    donation_id: Mapped[int] = mapped_column(ForeignKey("donations.id"), nullable=False, index=True)
    blood_bank_id: Mapped[int] = mapped_column(ForeignKey("blood_banks.id"), nullable=False, index=True)
    blood_group_id: Mapped[int] = mapped_column(ForeignKey("blood_groups.id"), nullable=False, index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("blood_components.id"), nullable=False, index=True)
    collection_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    processing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    screening_status: Mapped[str] = mapped_column(String(40), nullable=False, default="Pending", index=True)
    inventory_status: Mapped[str] = mapped_column(String(40), nullable=False, default="Testing Pending", index=True)
    storage_location: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    donation: Mapped["Donation"] = relationship(back_populates="units")
    blood_bank: Mapped["BloodBank"] = relationship()
    blood_group: Mapped["BloodGroup"] = relationship()
    component: Mapped["BloodComponent"] = relationship()
    screening_records: Mapped[list["ScreeningRecord"]] = relationship(back_populates="unit")

    __table_args__ = (
        Index("ix_units_status_group_comp_expiry", "inventory_status", "blood_group_id", "component_id", "expiry_date"),
    )


# ---------------------------------------------------------------------------
# Screening Table
# ---------------------------------------------------------------------------


class ScreeningRecord(Base):
    __tablename__ = "screening_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screening_reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("blood_units.id"), nullable=False, index=True)
    screening_status: Mapped[str] = mapped_column(String(40), nullable=False)
    screening_date: Mapped[date] = mapped_column(Date, nullable=False)
    result_reference: Mapped[str] = mapped_column(String(80), nullable=False, default="LAB-REF")
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reference_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    unit: Mapped["BloodUnit"] = relationship(back_populates="screening_records")


# ---------------------------------------------------------------------------
# Request & Allocation Tables
# ---------------------------------------------------------------------------


class BloodRequest(Base):
    __tablename__ = "blood_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    blood_bank_id: Mapped[int] = mapped_column(ForeignKey("blood_banks.id"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), nullable=False, index=True)
    blood_group_id: Mapped[int] = mapped_column(ForeignKey("blood_groups.id"), nullable=False, index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("blood_components.id"), nullable=False, index=True)
    required_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    fulfilled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urgency: Mapped[str] = mapped_column(String(32), nullable=False, default="Routine", index=True)
    request_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    required_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="Submitted", index=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")

    blood_bank: Mapped["BloodBank"] = relationship()
    hospital: Mapped["Hospital"] = relationship()
    blood_group: Mapped["BloodGroup"] = relationship()
    component: Mapped["BloodComponent"] = relationship()
    allocations: Mapped[list["BloodAllocation"]] = relationship(back_populates="request")

    __table_args__ = (
        CheckConstraint("required_quantity > 0", name="ck_request_required_positive"),
        CheckConstraint("fulfilled_quantity >= 0", name="ck_request_fulfilled_nonnegative"),
    )


class BloodAllocation(Base):
    __tablename__ = "blood_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id"), nullable=False, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("blood_units.id"), nullable=False, index=True)
    allocation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    allocated_by: Mapped[str] = mapped_column(String(80), nullable=False)
    allocation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="Reserved", index=True)
    issue_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    policy_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    request: Mapped["BloodRequest"] = relationship(back_populates="allocations")
    unit: Mapped["BloodUnit"] = relationship()


# ---------------------------------------------------------------------------
# Inventory Transaction Table
# ---------------------------------------------------------------------------


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("blood_units.id"), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False, default="UNIT")
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    performed_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    unit: Mapped["BloodUnit"] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_transaction_quantity_positive"),
    )


# ---------------------------------------------------------------------------
# Analytical & Threshold Tables
# ---------------------------------------------------------------------------


class ForecastResult(Base):
    __tablename__ = "forecast_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blood_group_id: Mapped[int] = mapped_column(ForeignKey("blood_groups.id"), nullable=False, index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("blood_components.id"), nullable=False, index=True)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    predicted_demand: Mapped[float] = mapped_column(Float, nullable=False)
    lower_bound: Mapped[float] = mapped_column(Float, nullable=False)
    upper_bound: Mapped[float] = mapped_column(Float, nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    blood_group: Mapped["BloodGroup"] = relationship()
    component: Mapped["BloodComponent"] = relationship()


class StockThreshold(Base):
    __tablename__ = "stock_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blood_bank_id: Mapped[int] = mapped_column(ForeignKey("blood_banks.id"), nullable=False, index=True)
    blood_group_id: Mapped[int] = mapped_column(ForeignKey("blood_groups.id"), nullable=False, index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("blood_components.id"), nullable=False, index=True)
    minimum_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    warning_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    critical_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    blood_bank: Mapped["BloodBank"] = relationship()
    blood_group: Mapped["BloodGroup"] = relationship()
    component: Mapped["BloodComponent"] = relationship()

    __table_args__ = (
        UniqueConstraint("blood_bank_id", "blood_group_id", "component_id", name="uq_threshold_bank_group_comp"),
        CheckConstraint("minimum_stock >= 0", name="ck_threshold_min_stock_nonneg"),
        CheckConstraint("warning_days >= critical_days", name="ck_threshold_warning_ge_critical"),
        CheckConstraint("critical_days >= 1", name="ck_threshold_critical_positive"),
    )


# ---------------------------------------------------------------------------
# Audit, Auth, Settings & ETL Tables
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="Administrator")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_name: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    setting_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ETLRunLog(Base):
    __tablename__ = "etl_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_reference: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    records_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    execution_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


# ---------------------------------------------------------------------------
# Surgical Pre-Reservation, Cold-Chain Transport & Service Billing Tables
# ---------------------------------------------------------------------------


class SurgicalBooking(Base):
    __tablename__ = "surgical_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_reference: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), nullable=False, index=True)
    blood_bank_id: Mapped[int] = mapped_column(ForeignKey("blood_banks.id"), nullable=False, index=True)
    blood_group_id: Mapped[int] = mapped_column(ForeignKey("blood_groups.id"), nullable=False)
    component_id: Mapped[int] = mapped_column(ForeignKey("blood_components.id"), nullable=False)
    procedure_category: Mapped[str] = mapped_column(String(100), nullable=False)
    surgery_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hold_until_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Reserved", index=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    request: Mapped["BloodRequest"] = relationship()
    hospital: Mapped["Hospital"] = relationship()
    blood_bank: Mapped["BloodBank"] = relationship()
    blood_group: Mapped["BloodGroup"] = relationship()
    component: Mapped["BloodComponent"] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_surgical_booking_qty_positive"),
    )


class TransportDispatch(Base):
    __tablename__ = "transport_dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dispatch_reference: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id"), nullable=False, index=True)
    blood_bank_id: Mapped[int] = mapped_column(ForeignKey("blood_banks.id"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), nullable=False, index=True)
    transport_mode: Mapped[str] = mapped_column(String(80), nullable=False)
    vehicle_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    courier_name: Mapped[str] = mapped_column(String(100), nullable=False)
    container_id: Mapped[str] = mapped_column(String(64), nullable=False)
    required_temp_range: Mapped[str] = mapped_column(String(64), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    eta_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Scheduled", index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    request: Mapped["BloodRequest"] = relationship()
    blood_bank: Mapped["BloodBank"] = relationship()
    hospital: Mapped["Hospital"] = relationship()


class ServicePayment(Base):
    __tablename__ = "service_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_reference: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id"), nullable=False, index=True)
    dispatch_id: Mapped[int | None] = mapped_column(ForeignKey("transport_dispatches.id"), nullable=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), nullable=False, index=True)
    component_service_fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transport_fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    payment_method: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="Paid", index=True)
    transaction_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    request: Mapped["BloodRequest"] = relationship()
    dispatch: Mapped["TransportDispatch | None"] = relationship()
    hospital: Mapped["Hospital"] = relationship()

    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_payment_total_nonneg"),
    )
