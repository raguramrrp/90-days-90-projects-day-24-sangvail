"""Donation and synthetic donor management service."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.auth import log_audit
from backend.models import BloodBank, BloodComponent, BloodUnit, Donation, Donor
from backend.schemas import BloodUnitCreate, DonationCreate, DonorCreate
from backend.services.inventory_service import create_blood_unit
from backend.validators.integrity import DomainValidationError, get_blood_group_by_name, get_component_by_name

VALID_DONATION_TRANSITIONS: dict[str, set[str]] = {
    "Registered": {"Collected", "Rejected"},
    "Collected": {"Processing", "Rejected"},
    "Processing": {"Completed", "Rejected"},
    "Completed": set(),
    "Rejected": set(),
}


def create_donor(session: Session, payload: DonorCreate, actor: str = "admin") -> Donor:
    """Register a fictional demonstration donor record."""
    existing = session.scalar(select(Donor).where(Donor.donor_reference == payload.donor_reference.strip()))
    if existing:
        raise DomainValidationError(f"Donor reference '{payload.donor_reference}' already exists.")
    bg = get_blood_group_by_name(session, payload.blood_group)
    donor = Donor(
        donor_reference=payload.donor_reference.strip(),
        full_name=payload.full_name.strip(),
        age_band=payload.age_band.strip(),
        blood_group_id=bg.id,
        contact=payload.contact.strip(),
        registration_date=payload.registration_date,
        status=payload.status.strip(),
    )
    session.add(donor)
    session.flush()
    log_audit(
        session,
        action="CREATE_DONOR",
        entity_type="donor",
        entity_id=donor.donor_reference,
        details=f"Registered synthetic donor ({bg.display_name}, {donor.age_band})",
        actor_name=actor,
    )
    return donor


def create_donation(session: Session, payload: DonationCreate, actor: str = "admin") -> Donation:
    """Create a new donation record traceable to an existing donor."""
    existing = session.scalar(
        select(Donation).where(Donation.donation_reference == payload.donation_reference.strip())
    )
    if existing:
        raise DomainValidationError(f"Donation reference '{payload.donation_reference}' already exists.")
    donor = session.scalar(select(Donor).where(Donor.donor_reference == payload.donor_reference.strip()))
    if not donor:
        raise DomainValidationError(f"Donor reference '{payload.donor_reference}' not found.")
    bank = session.get(BloodBank, payload.blood_bank_id)
    if not bank:
        raise DomainValidationError(f"Blood bank ID {payload.blood_bank_id} not found.")

    donation = Donation(
        donation_reference=payload.donation_reference.strip(),
        donor_id=donor.id,
        blood_bank_id=bank.id,
        donation_date=payload.donation_date,
        collection_location=payload.collection_location.strip(),
        collection_type=payload.collection_type.strip(),
        collection_status=payload.collection_status,
        collected_quantity=payload.collected_quantity,
        collection_staff=payload.collection_staff.strip(),
        notes=payload.notes.strip(),
        created_by=actor,
    )
    session.add(donation)
    session.flush()
    log_audit(
        session,
        action="CREATE_DONATION",
        entity_type="donation",
        entity_id=donation.donation_reference,
        details=f"Donor {donor.donor_reference}, {donation.collected_quantity} mL ({donation.collection_status})",
        actor_name=actor,
    )
    return donation


def update_donation_status(
    session: Session,
    donation_id: int,
    new_status: str,
    actor: str = "admin",
    notes: str = "",
) -> Donation:
    """Advance donation workflow status (Registered -> Collected -> Processing -> Completed/Rejected)."""
    donation = session.get(Donation, donation_id)
    if not donation:
        raise DomainValidationError(f"Donation ID {donation_id} not found.")
    allowed = VALID_DONATION_TRANSITIONS.get(donation.collection_status, set())
    if new_status != donation.collection_status and new_status not in allowed:
        raise DomainValidationError(
            f"Cannot transition donation '{donation.donation_reference}' from "
            f"'{donation.collection_status}' to '{new_status}'."
        )
    old = donation.collection_status
    donation.collection_status = new_status
    if notes:
        donation.notes = f"{donation.notes} | {notes}".strip(" |")
    log_audit(
        session,
        action="UPDATE_DONATION_STATUS",
        entity_type="donation",
        entity_id=donation.donation_reference,
        details=f"{old} -> {new_status}. {notes}".strip(),
        actor_name=actor,
    )
    return donation


def produce_component_units_from_donation(
    session: Session,
    donation_id: int,
    component_names: list[str],
    storage_location: str,
    processing_date: Optional[date] = None,
    actor: str = "admin",
) -> list[BloodUnit]:
    """Produce one or more component units from a valid collected/processing donation."""
    donation = session.scalar(
        select(Donation)
        .options(joinedload(Donation.donor).joinedload(Donor.blood_group))
        .where(Donation.id == donation_id)
    )
    if not donation:
        raise DomainValidationError(f"Donation ID {donation_id} not found.")
    if donation.collection_status in ("Registered", "Rejected"):
        raise DomainValidationError(
            f"Donation '{donation.donation_reference}' with status '{donation.collection_status}' "
            "cannot produce component units."
        )
    if not component_names:
        raise DomainValidationError("Select at least one component to produce from the donation.")

    proc_date = processing_date or donation.donation_date
    if proc_date < donation.donation_date:
        raise DomainValidationError("Processing date cannot precede donation date.")

    existing_count = session.query(BloodUnit).filter(BloodUnit.donation_id == donation.id).count()
    created_units: list[BloodUnit] = []
    for idx, comp_name in enumerate(component_names, start=existing_count + 1):
        comp: BloodComponent = get_component_by_name(session, comp_name)
        expiry = donation.donation_date + timedelta(days=comp.default_shelf_life_days)
        unit_ref = f"SV-{donation.donation_reference.replace('DN-', '')}-{comp.short_code}{idx}"
        payload = BloodUnitCreate(
            unit_reference=unit_ref,
            donation_reference=donation.donation_reference,
            blood_bank_id=donation.blood_bank_id,
            blood_group=donation.donor.blood_group.display_name,
            component_name=comp.component_name,
            collection_date=donation.donation_date,
            processing_date=proc_date,
            expiry_date=expiry,
            storage_location=storage_location,
            screening_status="Pending",
            inventory_status="Testing Pending",
        )
        unit = create_blood_unit(session, payload, actor=actor)
        created_units.append(unit)

    donation.collection_status = "Completed"
    log_audit(
        session,
        action="PRODUCE_COMPONENTS",
        entity_type="donation",
        entity_id=donation.donation_reference,
        details=f"Produced {len(created_units)} unit(s): {', '.join(u.unit_reference for u in created_units)}",
        actor_name=actor,
    )
    return created_units


def list_donations_df(
    session: Session,
    blood_bank_id: Optional[int] = None,
    blood_groups: Optional[list[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    statuses: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Fetch donation register joined with synthetic donor info and produced unit counts."""
    stmt = (
        select(Donation)
        .options(
            joinedload(Donation.donor).joinedload(Donor.blood_group),
            joinedload(Donation.blood_bank),
            joinedload(Donation.units),
        )
        .order_by(Donation.donation_date.desc(), Donation.id.desc())
    )
    if blood_bank_id:
        stmt = stmt.where(Donation.blood_bank_id == blood_bank_id)
    if start_date:
        stmt = stmt.where(Donation.donation_date >= start_date)
    if end_date:
        stmt = stmt.where(Donation.donation_date <= end_date)

    donations = session.scalars(stmt).unique().all()
    rows = []
    for d in donations:
        bg = d.donor.blood_group.display_name
        if blood_groups and bg not in blood_groups:
            continue
        if statuses and d.collection_status not in statuses:
            continue
        rows.append(
            {
                "id": d.id,
                "donation_reference": d.donation_reference,
                "donor_reference": d.donor.donor_reference,
                "donor_name": d.donor.full_name,
                "blood_group": bg,
                "donation_date": d.donation_date,
                "collection_location": d.collection_location,
                "collection_type": d.collection_type,
                "collected_quantity": d.collected_quantity,
                "collection_staff": d.collection_staff,
                "collection_status": d.collection_status,
                "units_produced": len(d.units),
                "notes": d.notes,
            }
        )
    return pd.DataFrame(rows)


def list_donors_df(session: Session, blood_groups: Optional[list[str]] = None) -> pd.DataFrame:
    """List synthetic demonstration donors."""
    stmt = select(Donor).options(joinedload(Donor.blood_group)).order_by(Donor.donor_reference.asc())
    donors = session.scalars(stmt).all()
    rows = []
    for dn in donors:
        bg = dn.blood_group.display_name
        if blood_groups and bg not in blood_groups:
            continue
        rows.append(
            {
                "id": dn.id,
                "donor_reference": dn.donor_reference,
                "full_name": dn.full_name,
                "age_band": dn.age_band,
                "blood_group": bg,
                "contact": dn.contact,
                "registration_date": dn.registration_date,
                "status": dn.status,
            }
        )
    return pd.DataFrame(rows)
