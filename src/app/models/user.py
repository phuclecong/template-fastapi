"""User model: an account holding exactly one Role by identity."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.time import utcnow
from app.models.role import ADMIN_ROLE_ID

if TYPE_CHECKING:
    from app.models.role import Role


def normalize_email(email: str) -> str:
    """Lowercase and trim an email for case-insensitive uniqueness."""
    return email.strip().lower()


class User(Base):
    """A person with an account, identified by a unique, case-insensitive email."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("roles.id", ondelete="RESTRICT"), index=True
    )
    # Async ORM cannot lazy-load: selectin makes every User load carry its Role.
    role: Mapped[Role] = relationship(lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @hybrid_property
    def is_administrator(self) -> bool:
        """Whether this User holds the Administrator System Role."""
        return self.role_id == ADMIN_ROLE_ID


__all__ = ["User", "normalize_email", "utcnow"]
