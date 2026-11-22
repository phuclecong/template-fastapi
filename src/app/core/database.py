"""Async SQLAlchemy engine, session factory, and declarative base."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def connect_args_for(database_url: str) -> dict[str, object]:
    """Driver arguments required by ``database_url``.

    Transaction-mode poolers (PgBouncer, Supavisor on Supabase port 6543) do not
    support named prepared statements, so disable both the asyncpg and SQLAlchemy
    statement caches. Session-mode/direct connections tolerate this setting.
    """
    if database_url.startswith("postgresql+asyncpg://"):
        return {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    return {}


_settings = get_settings()
engine = create_async_engine(
    _settings.database_url, connect_args=connect_args_for(_settings.database_url)
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """FastAPI dependency returning the session factory.

    Endpoints that outlive the request (such as the SSE stream) use this to open
    short-lived sessions instead of holding the request-scoped one open.
    """
    return async_session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
