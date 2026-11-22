"""Timezone helpers shared by models, schemas, and endpoints."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as a timezone-aware UTC datetime.

    SQLite has no real timezone support, so ``DateTime(timezone=True)`` columns read
    back naive; production (PostgreSQL) returns aware values. Normalizing lets code
    compare against :func:`utcnow` regardless of backend.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def to_utc(value: datetime | None) -> datetime | None:
    """Normalize an explicit-offset instant to UTC for backend-independent comparison."""
    return value.astimezone(UTC) if value is not None else None
