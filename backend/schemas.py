"""Pydantic v2 validation schemas for SANGVAIL operations."""

from __future__ import annotations

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import (
    BLOOD_GROUP_NAMES,
    DONATION_STATUSES,
    INVENTORY_STATUSES,
    REQUEST_URGENCIES,
    SCREENING_STATUSES,
)


class BloodUnitCreate(BaseModel):
    unit_reference: str = Field(..., min_length=3, max_length=40)
    donation_reference: str = Field(..., min_length=3, max_length=40)
    blood_bank_id: int = Field(..., gt=0)
    blood_group: str
    component_name: str = Field(..., min_length=2, max_length=80)
    collection_date: date
    processing_date: Optional[date] = None
    expiry_date: date
    storage_location: str = Field(..., min_length=2, max_length=120)
    screening_status: str = "Pending"
    inventory_status: str = "Testing Pending"

    @field_validator("blood_group")
    @classmethod
    def validate_blood_group(cls, value: str) -> str:
        if value not in BLOOD_GROUP_NAMES:
            raise ValueError(f"Unsupported blood group '{value}'. Must be one of {BLOOD_GROUP_NAMES}.")
        return value

    @field_validator("screening_status")
    @classmethod
    def validate_screening_status(cls, value: str) -> str:
        if value not in SCREENING_STATUSES:
            raise ValueError(f"Unsupported screening status '{value}'.")
        return value

    @field_validator("inventory_status")
    @classmethod
    def validate_inventory_status(cls, value: str) -> str:
        if value not in INVENTORY_STATUSES:
            raise ValueError(f"Unsupported inventory status '{value}'.")
        return value

    @model_validator(mode="after")
    def validate_dates_and_release_rules(self) -> "BloodUnitCreate":
        if self.processing_date is not None and self.processing_date < self.collection_date:
            raise ValueError("Processing date cannot be earlier than collection date.")
        if self.expiry_date <= self.collection_date:
            raise ValueError("Expiry date must be later than collection date.")
        if self.inventory_status == "Released" and self.screening_status != "Cleared":
            raise ValueError(
                "A blood unit cannot be created with 'Released' status unless screening is 'Cleared'."
            )
        return self


class DonorCreate(BaseModel):
    donor_reference: str = Field(..., min_length=3, max_length=40)
    full_name: str = Field(..., min_length=2, max_length=120)
    age_band: str = Field(..., min_length=2, max_length=24)
    blood_group: str
    contact: str = Field(..., min_length=3, max_length=120)
    registration_date: date
    status: str = "Active"

    @field_validator("blood_group")
    @classmethod
    def validate_blood_group(cls, value: str) -> str:
        if value not in BLOOD_GROUP_NAMES:
            raise ValueError(f"Unsupported blood group '{value}'.")
        return value


class DonationCreate(BaseModel):
    donation_reference: str = Field(..., min_length=3, max_length=40)
    donor_reference: str = Field(..., min_length=3, max_length=40)
    blood_bank_id: int = Field(..., gt=0)
    donation_date: date
    collection_location: str = Field(..., min_length=2, max_length=140)
    collection_type: str = Field(..., min_length=2, max_length=64)
    collection_status: str = "Collected"
    collected_quantity: int = Field(..., gt=0, le=1000)
    collection_staff: str = Field(..., min_length=2, max_length=100)
    notes: str = ""

    @field_validator("collection_status")
    @classmethod
    def validate_collection_status(cls, value: str) -> str:
        if value not in DONATION_STATUSES:
            raise ValueError(f"Unsupported collection status '{value}'.")
        return value


class ScreeningDecision(BaseModel):
    unit_id: int = Field(..., gt=0)
    new_screening_status: str
    target_inventory_status: str
    result_reference: str = Field(..., min_length=2, max_length=80)
    reference_note: str = ""
    reviewed_by: str = Field(..., min_length=2, max_length=80)

    @field_validator("new_screening_status")
    @classmethod
    def validate_screening(cls, value: str) -> str:
        if value not in SCREENING_STATUSES:
            raise ValueError(f"Invalid screening status '{value}'.")
        return value

    @field_validator("target_inventory_status")
    @classmethod
    def validate_inv_status(cls, value: str) -> str:
        allowed = {"Testing Pending", "Quarantined", "Released", "Rejected"}
        if value not in allowed:
            raise ValueError(f"Screening action can only set status to one of {sorted(allowed)}.")
        return value


class BloodRequestCreate(BaseModel):
    request_reference: str = Field(..., min_length=3, max_length=40)
    blood_bank_id: int = Field(..., gt=0)
    hospital_id: int = Field(..., gt=0)
    blood_group: str
    component_name: str = Field(..., min_length=2, max_length=80)
    required_quantity: int = Field(..., gt=0, le=200)
    urgency: str = "Routine"
    request_date: date
    required_date: date
    notes: str = ""

    @field_validator("blood_group")
    @classmethod
    def validate_bg(cls, value: str) -> str:
        if value not in BLOOD_GROUP_NAMES:
            raise ValueError(f"Unsupported blood group '{value}'.")
        return value

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, value: str) -> str:
        if value not in REQUEST_URGENCIES:
            raise ValueError(f"Invalid urgency '{value}'. Must be one of {REQUEST_URGENCIES}.")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "BloodRequestCreate":
        if self.required_date < self.request_date:
            raise ValueError("Required date cannot be earlier than request date.")
        return self


class ThresholdUpdate(BaseModel):
    blood_bank_id: int = Field(..., gt=0)
    blood_group_id: int = Field(..., gt=0)
    component_id: int = Field(..., gt=0)
    minimum_stock: int = Field(..., ge=0, le=500)
    warning_days: int = Field(..., ge=1, le=365)
    critical_days: int = Field(..., ge=1, le=365)

    @model_validator(mode="after")
    def validate_windows(self) -> "ThresholdUpdate":
        if self.critical_days > self.warning_days:
            raise ValueError("Critical expiry window cannot exceed warning expiry window.")
        return self
