"""Registration tests: POST /api/v1/auth/register."""

from typing import Any

import jwt
from httpx import AsyncClient

from app.core.config import get_settings

_DEFAULT_PASSWORD = "correct horse battery staple"


def _register(
    client: AsyncClient,
    *,
    name: str = "Ada Lovelace",
    email: str = "ada@example.com",
    password: str = _DEFAULT_PASSWORD,
) -> Any:
    return client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )


async def test_register_returns_201_with_tokens_and_member_user(client: AsyncClient) -> None:
    response = await _register(client)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"accessToken", "refreshToken", "user"}

    user = body["user"]
    assert set(user) == {"id", "name", "email", "role", "createdAt"}
    assert user["name"] == "Ada Lovelace"
    assert user["email"] == "ada@example.com"
    assert user["role"] == "member"
    assert user["id"]

    assert body["accessToken"]
    assert body["refreshToken"]
    assert body["accessToken"] != body["refreshToken"]

    claims = jwt.decode(
        body["accessToken"],
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
    )
    assert claims["sub"] == user["id"]
    assert isinstance(claims["sid"], str) and claims["sid"]
    assert claims["exp"] > claims["iat"]


async def test_email_is_lowercased_and_trimmed(client: AsyncClient) -> None:
    response = await _register(client, email="  Alice@Example.COM  ")

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "alice@example.com"


async def test_duplicate_email_is_case_insensitive_409(client: AsyncClient) -> None:
    first = await _register(client, email="Alice@Example.com")
    assert first.status_code == 201

    second = await _register(client, email="alice@example.com")

    assert second.status_code == 409
    body = second.json()
    assert set(body) == {"type", "title", "status", "detail", "code"}
    assert body["status"] == 409
    assert body["code"] == "conflict"


async def test_password_must_be_at_least_8_characters(client: AsyncClient) -> None:
    response = await _register(client, password="short")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_invalid_email_returns_422(client: AsyncClient) -> None:
    response = await _register(client, email="not-an-email")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
