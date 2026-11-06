"""Rate-limit tests: auth endpoints return 429 ``too_many_requests`` past the limit."""

from typing import Any

from httpx import AsyncClient

from app.core.ratelimit import SlidingWindowRateLimiter, get_auth_rate_limiter
from app.main import app

_LIMIT = 3
_PASSWORD = "correct horse battery staple"


def _install_limiter() -> None:
    limiter = SlidingWindowRateLimiter(_LIMIT, window_seconds=3600)
    app.dependency_overrides[get_auth_rate_limiter] = lambda: limiter


def _assert_too_many_requests(response: Any) -> None:
    assert response.status_code == 429
    body = response.json()
    assert set(body) == {"type", "title", "status", "detail", "code"}
    assert body["status"] == 429
    assert body["code"] == "too_many_requests"
    assert body["type"].endswith("/too_many_requests")
    assert body["title"] == "Too many requests"


async def test_login_is_rate_limited(client: AsyncClient) -> None:
    _install_limiter()

    for _ in range(_LIMIT):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "ada@example.com", "password": "wrong password here"},
        )
        assert response.status_code == 401

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "wrong password here"},
    )
    _assert_too_many_requests(response)


async def test_register_is_rate_limited(client: AsyncClient) -> None:
    _install_limiter()

    for index in range(_LIMIT):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "name": f"User {index}",
                "email": f"user{index}@example.com",
                "password": _PASSWORD,
            },
        )
        assert response.status_code == 201

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "User Over",
            "email": "user-over@example.com",
            "password": _PASSWORD,
        },
    )
    _assert_too_many_requests(response)


async def test_refresh_is_rate_limited(client: AsyncClient) -> None:
    _install_limiter()

    for _ in range(_LIMIT):
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": "not-a-real-token"},
        )
        assert response.status_code == 401

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": "not-a-real-token"},
    )
    _assert_too_many_requests(response)
