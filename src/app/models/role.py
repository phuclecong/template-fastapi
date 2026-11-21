"""Role entity and Role status (see GLOSSARY and ADR-0004)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.time import utcnow

ADMIN_ROLE_ID = "rol_admin"
MEMBER_ROLE_ID = "rol_member"
SYSTEM_ROLE_IDS = frozenset({ADMIN_ROLE_ID, MEMBER_ROLE_ID})


def new_role_id() -> str:
    """Return a ``rol_``-prefixed UUID v4 identity for a custom Role."""
    return f"rol_{uuid4()}"


class RoleStatus(StrEnum):
    """Whether a Role is assignable (see GLOSSARY: Role status)."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class Role(Base):
    """An assignable Role a User holds; System Roles have fixed identities."""

    __tablename__ = "roles"
    __table_args__ = (
        # Case-insensitive uniqueness: ``Administrator`` and ``administrator`` collide.
        Index("ix_roles_title_lower", text("lower(title)"), unique=True),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_role_id)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=RoleStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    @property
    def is_system(self) -> bool:
        """Whether this is one of the two fixed System Roles."""
        return self.id in SYSTEM_ROLE_IDS
