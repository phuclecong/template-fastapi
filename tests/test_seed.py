"""First-admin seed tests.

The seed is an operator action with no HTTP seam, so it is exercised at its
function boundary against a real per-test SQLite database (no mocks).
"""

from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from pytest import MonkeyPatch
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models as _models  # noqa: F401  # ensure models register with Base.metadata
from app.core.config import Settings
from app.core.database import Base
from app.core.seed import seed_admin
from app.models.user import User


def _settings(**overrides: Any) -> Settings:
    """Build Settings without reading a ``.env`` file."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


async def _build_db(
    tmp_path: Path, name: str
) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def test_seed_creates_admin_from_env(tmp_path: Path) -> None:
    factory, engine = await _build_db(tmp_path, "seed.db")
    settings = _settings(
        admin_name="Root Admin",
        admin_email="  ADMIN@Example.com ",
        admin_password="admin-password-123",
    )

    await seed_admin(factory, settings)

    async with factory() as db:
        user = await db.scalar(select(User).where(User.email == "admin@example.com"))

    assert user is not None
    assert user.name == "Root Admin"
    assert user.email == "admin@example.com"
    assert user.role == "admin"
    PasswordHasher().verify(user.hashed_password, "admin-password-123")  # raises on mismatch

    await engine.dispose()


async def test_seed_is_idempotent(tmp_path: Path) -> None:
    factory, engine = await _build_db(tmp_path, "seed.db")
    settings = _settings(
        admin_email="admin@example.com",
        admin_password="admin-password-123",
    )

    await seed_admin(factory, settings)
    await seed_admin(factory, settings)

    async with factory() as db:
        count = await db.scalar(select(func.count()).select_from(User))

    assert count == 1

    await engine.dispose()


async def test_seed_noops_when_admin_env_is_unset(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    factory, engine = await _build_db(tmp_path, "seed.db")
    for name in ("ADMIN_EMAIL", "admin_email", "ADMIN_PASSWORD", "admin_password"):
        monkeypatch.delenv(name, raising=False)

    await seed_admin(factory, _settings())

    async with factory() as db:
        count = await db.scalar(select(func.count()).select_from(User))

    assert count == 0

    await engine.dispose()
