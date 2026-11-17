"""Authentication, password hashing, and audit logging for SANGVAIL."""

from __future__ import annotations

from typing import Optional
import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import AuditLog, User


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    """Authenticate an active user against the users table."""
    user = session.scalar(select(User).where(User.username == username.strip(), User.active.is_(True)))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def register_patient_user(
    session: Session,
    username: str,
    password: str,
    display_name: str,
) -> User:
    """Register a new Patient / User portal account with bcrypt password hashing."""
    uname = username.strip().lower()
    dname = display_name.strip()
    if len(uname) < 3 or not uname.replace("_", "").replace(".", "").isalnum():
        raise ValueError("Username must be at least 3 characters (letters, numbers, underscore, or dot).")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    if len(dname) < 2:
        raise ValueError("Full name must be at least 2 characters long.")

    existing = session.scalar(select(User).where(User.username == uname))
    if existing:
        raise ValueError(f"Username '{uname}' is already registered. Please choose another.")

    user = User(
        username=uname,
        password_hash=hash_password(password),
        display_name=dname,
        role="Patient",
        active=True,
    )
    session.add(user)
    session.flush()
    log_audit(
        session,
        action="REGISTER_PATIENT_USER",
        entity_type="user",
        entity_id=uname,
        details=f"Registered Patient/User portal account ({dname})",
        actor_name=uname,
        user_id=user.id,
    )
    return user


def log_audit(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    details: str = "",
    actor_name: str = "admin",
    user_id: Optional[int] = None,
) -> AuditLog:
    """Append an immutable audit log record to the current transaction."""
    entry = AuditLog(
        user_id=user_id,
        actor_name=actor_name,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details,
    )
    session.add(entry)
    return entry
