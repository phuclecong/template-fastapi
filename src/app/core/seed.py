"""Deterministic System Role and first-admin seeding (see ADR-0004)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password, validate_password
from app.models.role import (
    ADMIN_ROLE_ID,
    MEMBER_ROLE_ID,
    SYSTEM_ROLE_IDS,
    Role,
    RoleStatus,
)
from app.models.user import User, normalize_email

# Fixed instants keep the seed deterministic across migrations and startups.
SYSTEM_ROLE_TIMESTAMP = datetime(2024, 1, 1, tzinfo=UTC)

SYSTEM_ROLE_SEEDS: tuple[dict[str, str], ...] = (
    {
        "id": ADMIN_ROLE_ID,
        "title": "Administrator",
        "description": "Full access to workspace administration.",
        "status": RoleStatus.ACTIVE.value,
    },
    {
        "id": MEMBER_ROLE_ID,
        "title": "Member",
        "description": "Standard workspace member.",
        "status": RoleStatus.ACTIVE.value,
    },
)


async def seed_system_roles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ensure the two System Roles exist, idempotently.

    Runs at application startup and in test fixtures so a database created from
    metadata (never migrated) still has the Administrator and Member Roles.
    """
    async with session_factory() as session:
        existing = set(
            (await session.scalars(select(Role.id).where(Role.id.in_(SYSTEM_ROLE_IDS)))).all()
        )
        for seed in SYSTEM_ROLE_SEEDS:
            if seed["id"] not in existing:
                session.add(
                    Role(
                        id=seed["id"],
                        title=seed["title"],
                        description=seed["description"],
                        status=seed["status"],
                        created_at=SYSTEM_ROLE_TIMESTAMP,
                        updated_at=SYSTEM_ROLE_TIMESTAMP,
                    )
                )
        await session.commit()


async def seed_admin(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Create the first Administrator from settings, idempotently, if configured.

    ADMIN_EMAIL and ADMIN_PASSWORD must be set together; registration always
    produces a ``rol_member``, so this is the only way a ``rol_admin`` is born.
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
            role_id=ADMIN_ROLE_ID,
        )
        session.add(admin)
        await session.commit()
