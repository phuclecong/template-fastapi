"""Shared pytest fixtures.

The HTTP boundary is the single test seam: the ASGI app is driven through httpx's
``AsyncClient``, backed by a real per-test SQLite database (not mocks).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models as _models  # noqa: F401  # ensure models register with Base.metadata
from app.core.database import Base, get_db
from app.main import app


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """An AsyncClient bound to the app, backed by a fresh per-test SQLite database."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()
    await engine.dispose()
