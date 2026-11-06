"""Deterministic first-admin seed (see docs/adr/0003-fixed-two-role-authorization.md)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password, validate_password
from app.models.user import Role, User, normalize_email


async def seed_admin(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Create the first admin from settings, idempotently, if configured.

    ADMIN_EMAIL and ADMIN_PASSWORD must be set together; registration always
    produces a ``member``, so this is the only way an ``admin`` is born.
    """
    email = normalize_email(settings.admin_email or "")
    password = settings.admin_password or ""

    if not email and not password:
        return
    if not email or not password:
        raise RuntimeError("ADMIN_EMAIL and ADMIN_PASSWORD must be set together.")
    validate_password(password)

    async with session_factory() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            return

        admin = User(
            name=settings.admin_name,
            email=email,
            hashed_password=hash_password(password),
            role=Role.ADMIN.value,
        )
        session.add(admin)
        await session.commit()
