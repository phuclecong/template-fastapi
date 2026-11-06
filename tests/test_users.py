"""Users endpoint tests: GET /users, GET /users/me, PATCH /users/{id}/role, DELETE /users/{id}."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.user import Role, User

_PASSWORD = "correct horse battery staple"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(
    client: AsyncClient,
    *,
    name: str,
    email: str,
    password: str = _PASSWORD,
) -> Any:
    return client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": password},
    )


def _login(
    client: AsyncClient,
    *,
    email: str,
    password: str = _PASSWORD,
) -> Any:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _create_user(
    factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    email: str,
    role: Role,
    password: str = _PASSWORD,
) -> str:
    """Insert a user directly; the only way to seed an ``admin`` (members go via /register)."""
    user = User(
        name=name,
        email=email,
        hashed_password=hash_password(password),
        role=role.value,
    )
    async with factory() as db:
        db.add(user)
        await db.commit()
        return user.id


async def _create_admin(
    factory: async_sessionmaker[AsyncSession],
    *,
    name: str = "Admin",
    email: str = "admin@example.com",
) -> str:
    """Insert an admin directly (admins are born via seed, not /register)."""
    return await _create_user(factory, name=name, email=email, role=Role.ADMIN)


def _create_task(
    client: AsyncClient,
    *,
    token: str,
    assignee_id: str | None = None,
    title: str = "A task",
) -> Any:
    """Create a task via the API (optionally assigned), returning the response."""
    json: dict[str, Any] = {"title": title}
    if assignee_id is not None:
        json["assigneeId"] = assignee_id
    return client.post("/api/v1/tasks", json=json, headers=_auth(token))


async def test_me_returns_authenticated_user(client: AsyncClient) -> None:
    registered = await _register(client, name="Ada Lovelace", email="ada@example.com")
    access_token = registered.json()["accessToken"]
    registered_user = registered.json()["user"]

    response = await client.get("/api/v1/users/me", headers=_auth(access_token))

    assert response.status_code == 200
    assert response.json() == registered_user


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_list_users_returns_all_with_total_count(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    await _register(client, name="Ada Lovelace", email="ada@example.com")
    await _register(client, name="Grace Hopper", email="grace@example.com")
    member_token = (await _login(client, email="ada@example.com")).json()["accessToken"]

    response = await client.get("/api/v1/users", headers=_auth(member_token))

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    users = response.json()
    assert {user["email"] for user in users} == {
        "admin@example.com",
        "ada@example.com",
        "grace@example.com",
    }
    for user in users:
        assert set(user) == {"id", "name", "email", "role", "createdAt"}


async def test_list_users_paginates_with_start_and_end(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    await _register(client, name="Ada Lovelace", email="ada@example.com")
    await _register(client, name="Grace Hopper", email="grace@example.com")
    await _register(client, name="Linus Torvalds", email="linus@example.com")
    member_token = (await _login(client, email="ada@example.com")).json()["accessToken"]

    response = await client.get(
        "/api/v1/users",
        params={"_start": 1, "_end": 3},
        headers=_auth(member_token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "4"
    users = response.json()
    # Ordered by creation: admin, ada, grace, linus -> slice [1, 3) is ada + grace.
    assert [user["email"] for user in users] == ["ada@example.com", "grace@example.com"]


async def test_list_users_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_admin_promotes_member(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{member_id}/role",
        json={"role": "admin"},
        headers=_auth(admin_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == member_id
    assert body["role"] == "admin"


async def test_member_cannot_change_role(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_token = member.json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{admin_id}/role",
        json={"role": "member"},
        headers=_auth(member_token),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_demoting_last_admin_is_blocked(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _create_admin(session_factory)
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{admin_id}/role",
        json={"role": "member"},
        headers=_auth(admin_token),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_admin_can_be_demoted_when_another_admin_exists(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory, name="Admin One", email="admin1@example.com")
    admin2_id = await _create_admin(session_factory, name="Admin Two", email="admin2@example.com")
    admin1_token = (await _login(client, email="admin1@example.com")).json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{admin2_id}/role",
        json={"role": "member"},
        headers=_auth(admin1_token),
    )

    assert response.status_code == 200
    assert response.json()["role"] == "member"


async def test_update_role_unknown_user_returns_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/role",
        json={"role": "admin"},
        headers=_auth(admin_token),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_update_role_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/users/some-id/role",
        json={"role": "admin"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_update_role_invalid_role_returns_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{member_id}/role",
        json={"role": "superadmin"},
        headers=_auth(admin_token),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_admin_deletes_member_and_unassigns_their_tasks(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    member_token = member.json()["accessToken"]
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    task = await _create_task(client, token=member_token, assignee_id=member_id)
    task_id = task.json()["id"]

    response = await client.delete(f"/api/v1/users/{member_id}", headers=_auth(admin_token))

    assert response.status_code == 204

    # The member's account is gone…
    login_after = await _login(client, email="ada@example.com")
    assert login_after.status_code == 401

    # …but their tasks survive, unassigned.
    fetched = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(admin_token))
    assert fetched.status_code == 200
    assert fetched.json()["assigneeId"] is None


async def test_member_cannot_delete_user(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_token = member.json()["accessToken"]

    response = await client.delete(f"/api/v1/users/{admin_id}", headers=_auth(member_token))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_admin_cannot_delete_self_even_with_another_admin(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _create_admin(session_factory, name="Admin One", email="admin1@example.com")
    await _create_admin(session_factory, name="Admin Two", email="admin2@example.com")
    admin1_token = (await _login(client, email="admin1@example.com")).json()["accessToken"]

    response = await client.delete(f"/api/v1/users/{admin_id}", headers=_auth(admin1_token))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_admin_cannot_delete_last_admin(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _create_admin(session_factory)
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.delete(f"/api/v1/users/{admin_id}", headers=_auth(admin_token))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_admin_can_delete_another_admin_when_not_last(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory, name="Admin One", email="admin1@example.com")
    admin2_id = await _create_admin(session_factory, name="Admin Two", email="admin2@example.com")
    admin1_token = (await _login(client, email="admin1@example.com")).json()["accessToken"]

    response = await client.delete(f"/api/v1/users/{admin2_id}", headers=_auth(admin1_token))

    assert response.status_code == 204


async def test_delete_unknown_user_returns_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.delete(
        "/api/v1/users/00000000-0000-0000-0000-000000000000", headers=_auth(admin_token)
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_delete_user_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/users/some-id")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
