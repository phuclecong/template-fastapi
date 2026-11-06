"""Task model and its status/priority enums (see GLOSSARY)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utcnow


class Status(StrEnum):
    """A task's position in its lifecycle (see GLOSSARY)."""

    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    BLOCKED = "blocked"


class Priority(StrEnum):
    """A task's importance (see GLOSSARY)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Task(Base):
    """A unit of work on the shared board (see GLOSSARY)."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=Status.TODO.value)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
