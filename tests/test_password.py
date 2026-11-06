"""Password endpoint tests: PUT /api/v1/password."""

from typing import Any

from httpx import AsyncClient

_OLD_PASSWORD = "correct horse battery staple"
_NEW_PASSWORD = "brand new secret phrase"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(
    client: AsyncClient,
    *,
    email: str = "ada@example.com",
    password: str = _OLD_PASSWORD,
) -> Any:
    return client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": password},
    )


def _login(
    client: AsyncClient,
    *,
    email: str = "ada@example.com",
    password: str = _OLD_PASSWORD,
) -> Any:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _refresh(client: AsyncClient, *, refresh_token: str) -> Any:
    return client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})


def _update_password(
    client: AsyncClient,
    *,
    access_token: str,
    current_password: str,
    new_password: str,
) -> Any:
    return client.put(
        "/api/v1/password",
        json={"currentPassword": current_password, "newPassword": new_password},
        headers=_auth(access_token),
    )


async def test_update_password_returns_204_and_rotates_credentials(client: AsyncClient) -> None:
    registered = await _register(client, password=_OLD_PASSWORD)
    access_token = registered.json()["accessToken"]

    response = await _update_password(
        client,
        access_token=access_token,
        current_password=_OLD_PASSWORD,
        new_password=_NEW_PASSWORD,
    )

    assert response.status_code == 204

    old_login = await _login(client, password=_OLD_PASSWORD)
    assert old_login.status_code == 401

    new_login = await _login(client, password=_NEW_PASSWORD)
    assert new_login.status_code == 200


async def test_update_password_wrong_current_password_returns_400(client: AsyncClient) -> None:
    registered = await _register(client, password=_OLD_PASSWORD)
    access_token = registered.json()["accessToken"]

    response = await _update_password(
        client,
        access_token=access_token,
        current_password="totally wrong password",
        new_password=_NEW_PASSWORD,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"

    # The password was not changed.
    login = await _login(client, password=_OLD_PASSWORD)
    assert login.status_code == 200


async def test_update_password_revokes_other_sessions_keeps_current(client: AsyncClient) -> None:
    first = await _register(client, password=_OLD_PASSWORD)
    first_refresh = first.json()["refreshToken"]

    second = await _login(client, password=_OLD_PASSWORD)
    second_refresh = second.json()["refreshToken"]
    second_access = second.json()["accessToken"]

    response = await _update_password(
        client,
        access_token=second_access,
        current_password=_OLD_PASSWORD,
        new_password=_NEW_PASSWORD,
    )

    assert response.status_code == 204

    # The other session's refresh token is revoked…
    first_after = await _refresh(client, refresh_token=first_refresh)
    assert first_after.status_code == 401

    # …but the current session's refresh token still works.
    kept = await _refresh(client, refresh_token=second_refresh)
    assert kept.status_code == 200


async def test_update_password_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.put(
        "/api/v1/password",
        json={"currentPassword": _OLD_PASSWORD, "newPassword": _NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_update_password_short_new_password_returns_422(client: AsyncClient) -> None:
    registered = await _register(client, password=_OLD_PASSWORD)
    access_token = registered.json()["accessToken"]

    response = await _update_password(
        client,
        access_token=access_token,
        current_password=_OLD_PASSWORD,
        new_password="short",
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
