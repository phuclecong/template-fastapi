"""Shared helpers for HTTP-boundary tests."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.role import ADMIN_ROLE_ID
from app.models.user import User

PASSWORD = "correct horse battery staple"


def auth(token: str) -> dict[str, str]:
    """Return the bearer authorization header for ``token``."""
    return {"Authorization": f"Bearer {token}"}


async def create_admin(
    factory: async_sessionmaker[AsyncSession],
    *,
    name: str = "Admin",
    email: str = "admin@example.com",
) -> str:
    """Insert an Administrator directly; admins are born via seed, not /register."""
    user = User(
        name=name,
        email=email,
        hashed_password=hash_password(PASSWORD),
        role_id=ADMIN_ROLE_ID,
    )
    async with factory() as db:
        db.add(user)
        await db.commit()
        return user.id


async def admin_token(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
) -> str:
    """Seed an Administrator, log in, and return its access token."""
    await create_admin(factory)
    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["accessToken"]


async def member_token(client: AsyncClient, *, email: str = "ada@example.com") -> str:
    """Register a Member and return its access token."""
    registered = await client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": PASSWORD},
    )
    assert registered.status_code == 201
    return registered.json()["accessToken"]
