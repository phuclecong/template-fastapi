"""Session lifecycle tests: POST /api/v1/auth/login, /refresh, /logout."""

from typing import Any

import jwt
from httpx import AsyncClient

from app.core.config import get_settings

_PASSWORD = "correct horse battery staple"


def _register(
    client: AsyncClient,
    *,
    name: str = "Ada Lovelace",
    email: str = "ada@example.com",
    password: str = _PASSWORD,
) -> Any:
    return client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )


def _login(
    client: AsyncClient,
    *,
    email: str = "ada@example.com",
    password: str = _PASSWORD,
) -> Any:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_returns_200_with_tokens_and_user(client: AsyncClient) -> None:
    registered = await _register(client)
    user_id = registered.json()["user"]["id"]

    response = await _login(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"accessToken", "refreshToken", "user"}
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["role"] == "member"
    assert body["user"]["id"] == user_id
    assert body["accessToken"]
    assert body["refreshToken"]

    claims = jwt.decode(
        body["accessToken"],
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
    )
    assert claims["sub"] == user_id
    assert isinstance(claims["sid"], str) and claims["sid"]


async def test_login_wrong_password_returns_401(client: AsyncClient) -> None:
    await _register(client)

    response = await _login(client, password="wrong password here")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_login_unknown_email_returns_401(client: AsyncClient) -> None:
    response = await _login(client, email="nobody@example.com")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def _refresh(client: AsyncClient, *, refresh_token: str) -> Any:
    return client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})


def _sid(access_token: str) -> str:
    claims = jwt.decode(
        access_token,
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
    )
    return claims["sid"]


async def test_refresh_rotates_refresh_token_in_same_session(client: AsyncClient) -> None:
    registered = await _register(client)
    first = registered.json()

    response = await _refresh(client, refresh_token=first["refreshToken"])

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"accessToken", "refreshToken"}
    assert body["refreshToken"] != first["refreshToken"]
    assert body["refreshToken"]
    assert body["accessToken"]
    # Same session (sid unchanged), same user.
    assert _sid(body["accessToken"]) == _sid(first["accessToken"])


async def test_refresh_reuse_of_rotated_token_revokes_session(client: AsyncClient) -> None:
    registered = await _register(client)
    first = registered.json()

    rotated = await _refresh(client, refresh_token=first["refreshToken"])
    assert rotated.status_code == 200
    new_refresh = rotated.json()["refreshToken"]

    stale = await _refresh(client, refresh_token=first["refreshToken"])
    assert stale.status_code == 401
    assert stale.json()["code"] == "unauthorized"

    # The whole session is gone: even the rotated token now fails.
    revoked = await _refresh(client, refresh_token=new_refresh)
    assert revoked.status_code == 401


async def test_refresh_invalid_token_returns_401(client: AsyncClient) -> None:
    response = await _refresh(client, refresh_token="not-a-real-token")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def _logout(client: AsyncClient, *, access_token: str) -> Any:
    return client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )


async def test_logout_revokes_session_and_refresh_stops_working(client: AsyncClient) -> None:
    registered = await _register(client)
    body = registered.json()

    response = await _logout(client, access_token=body["accessToken"])

    assert response.status_code == 204

    after = await _refresh(client, refresh_token=body["refreshToken"])
    assert after.status_code == 401


async def test_logout_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_logout_is_idempotent(client: AsyncClient) -> None:
    registered = await _register(client)
    access_token = registered.json()["accessToken"]

    first = await _logout(client, access_token=access_token)
    second = await _logout(client, access_token=access_token)

    assert first.status_code == 204
    assert second.status_code == 204
