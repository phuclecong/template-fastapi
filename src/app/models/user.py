"""User model and the fixed two-role authorization enum."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    """Lowercase and trim an email for case-insensitive uniqueness."""
    return email.strip().lower()


class Role(StrEnum):
    """The two fixed roles (see docs/adr/0003-fixed-two-role-authorization.md)."""

    ADMIN = "admin"
    MEMBER = "member"


class User(Base):
    """A person with an account, identified by a unique, case-insensitive email."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.MEMBER.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
