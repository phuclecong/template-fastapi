"""Users endpoint tests: GET /users, GET /users/me, PATCH /users/{id}/role, DELETE /users/{id}."""

from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.role import ADMIN_ROLE_ID, MEMBER_ROLE_ID, Role
from app.models.user import User
from tests.helpers import PASSWORD as _PASSWORD
from tests.helpers import auth as _auth
from tests.helpers import create_admin as _create_admin


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
    role_id: str,
    password: str = _PASSWORD,
    created_at: datetime | None = None,
) -> str:
    """Insert a user directly; the only way to seed an Administrator (members register)."""
    user = User(
        name=name,
        email=email,
        hashed_password=hash_password(password),
        role_id=role_id,
    )
    if created_at is not None:
        user.created_at = created_at
    async with factory() as db:
        db.add(user)
        await db.commit()
        return user.id


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
        assert set(user) == {"id", "name", "email", "roleId", "role", "createdAt"}
        assert set(user["role"]) == {"id", "title", "status"}


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
    # Default sort is name: Ada, Admin, Grace, Linus -> slice [1, 3) is admin + grace.
    assert [user["email"] for user in users] == ["admin@example.com", "grace@example.com"]


async def test_list_users_filters_by_q_on_name_and_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    await _register(client, name="Ada Lovelace", email="ada@example.com")
    await _register(client, name="Grace Hopper", email="grace@example.com")
    member_token = (await _login(client, email="ada@example.com")).json()["accessToken"]

    by_name = await client.get("/api/v1/users", params={"q": "GRACE"}, headers=_auth(member_token))
    by_email = await client.get(
        "/api/v1/users", params={"q": "admin@"}, headers=_auth(member_token)
    )

    assert by_name.status_code == 200
    assert by_name.headers["x-total-count"] == "1"
    assert [user["email"] for user in by_name.json()] == ["grace@example.com"]

    assert by_email.status_code == 200
    assert by_email.headers["x-total-count"] == "1"
    assert [user["email"] for user in by_email.json()] == ["admin@example.com"]


async def test_list_users_filters_by_role_id(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_token = (await _login(client, email="ada@example.com")).json()["accessToken"]

    admins = await client.get(
        "/api/v1/users", params={"roleId": ADMIN_ROLE_ID}, headers=_auth(member_token)
    )
    members = await client.get(
        "/api/v1/users", params={"roleId": MEMBER_ROLE_ID}, headers=_auth(member_token)
    )

    assert admins.status_code == 200
    assert admins.headers["x-total-count"] == "1"
    assert [user["email"] for user in admins.json()] == ["admin@example.com"]
    assert members.status_code == 200
    assert members.headers["x-total-count"] == "1"
    assert [user["email"] for user in members.json()] == ["ada@example.com"]


async def test_list_users_sorts_by_name_desc(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory, name="Admin", email="admin@example.com")
    await _register(client, name="Ada Lovelace", email="ada@example.com")
    await _register(client, name="Grace Hopper", email="grace@example.com")
    member_token = (await _login(client, email="ada@example.com")).json()["accessToken"]

    response = await client.get(
        "/api/v1/users",
        params={"_sort": "name", "_order": "desc"},
        headers=_auth(member_token),
    )

    assert [user["name"] for user in response.json()] == ["Grace Hopper", "Admin", "Ada Lovelace"]


async def test_list_users_sorts_by_role_id(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory, name="Zed Admin", email="zadmin@example.com")
    await _register(client, name="A Member", email="amember@example.com")
    await _register(client, name="B Member", email="bmember@example.com")
    member_token = (await _login(client, email="amember@example.com")).json()["accessToken"]

    response = await client.get(
        "/api/v1/users", params={"_sort": "roleId"}, headers=_auth(member_token)
    )

    assert [user["roleId"] for user in response.json()] == [
        ADMIN_ROLE_ID,
        MEMBER_ROLE_ID,
        MEMBER_ROLE_ID,
    ]


async def test_list_users_sorts_by_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory, name="Zed Admin", email="aaron@example.com")
    await _register(client, name="Ada Lovelace", email="zulu@example.com")
    await _register(client, name="Mona Lisa", email="mike@example.com")
    member_token = (await _login(client, email="zulu@example.com")).json()["accessToken"]

    ascending = await client.get(
        "/api/v1/users", params={"_sort": "email"}, headers=_auth(member_token)
    )
    descending = await client.get(
        "/api/v1/users",
        params={"_sort": "email", "_order": "desc"},
        headers=_auth(member_token),
    )

    assert [user["email"] for user in ascending.json()] == [
        "aaron@example.com",
        "mike@example.com",
        "zulu@example.com",
    ]
    assert [user["email"] for user in descending.json()] == [
        "zulu@example.com",
        "mike@example.com",
        "aaron@example.com",
    ]


async def test_list_users_sorts_by_created_at(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_user(
        session_factory,
        name="Oldest",
        email="oldest@example.com",
        role_id=ADMIN_ROLE_ID,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    await _create_user(
        session_factory,
        name="Newest",
        email="newest@example.com",
        role_id=MEMBER_ROLE_ID,
        created_at=datetime(2024, 3, 1, tzinfo=UTC),
    )
    await _create_user(
        session_factory,
        name="Middle",
        email="middle@example.com",
        role_id=MEMBER_ROLE_ID,
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    token = (await _login(client, email="middle@example.com")).json()["accessToken"]

    ascending = await client.get(
        "/api/v1/users", params={"_sort": "createdAt"}, headers=_auth(token)
    )
    descending = await client.get(
        "/api/v1/users",
        params={"_sort": "createdAt", "_order": "desc"},
        headers=_auth(token),
    )

    assert [user["email"] for user in ascending.json()] == [
        "oldest@example.com",
        "middle@example.com",
        "newest@example.com",
    ]
    assert [user["email"] for user in descending.json()] == [
        "newest@example.com",
        "middle@example.com",
        "oldest@example.com",
    ]


async def test_list_users_role_id_filter_is_exact(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    token = member.json()["accessToken"]

    partial = await client.get("/api/v1/users", params={"roleId": "rol_adm"}, headers=_auth(token))
    exact = await client.get(
        "/api/v1/users", params={"roleId": MEMBER_ROLE_ID}, headers=_auth(token)
    )

    assert partial.status_code == 200
    assert partial.json() == []
    assert exact.status_code == 200
    assert [user["id"] for user in exact.json()] == [member_id]


async def test_list_users_total_count_reflects_filters(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    await _register(client, name="Ada Lovelace", email="ada@example.com")
    await _register(client, name="Grace Hopper", email="grace@example.com")
    member_token = (await _login(client, email="ada@example.com")).json()["accessToken"]

    response = await client.get(
        "/api/v1/users",
        params={"q": "example.com", "_start": 0, "_end": 2},
        headers=_auth(member_token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    assert len(response.json()) == 2


async def test_list_users_rejects_unknown_sort_field(client: AsyncClient) -> None:
    registered = await _register(client, name="Ada Lovelace", email="ada@example.com")
    token = registered.json()["accessToken"]

    response = await client.get("/api/v1/users", params={"_sort": "bogus"}, headers=_auth(token))

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_list_users_rejects_invalid_order(client: AsyncClient) -> None:
    registered = await _register(client, name="Ada Lovelace", email="ada@example.com")
    token = registered.json()["accessToken"]

    response = await client.get(
        "/api/v1/users", params={"_order": "sideways"}, headers=_auth(token)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_list_users_filters_by_unknown_role_id_returns_empty(client: AsyncClient) -> None:
    registered = await _register(client, name="Ada Lovelace", email="ada@example.com")
    token = registered.json()["accessToken"]

    response = await client.get(
        "/api/v1/users", params={"roleId": "rol_missing"}, headers=_auth(token)
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "0"
    assert response.json() == []


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
        json={"roleId": ADMIN_ROLE_ID},
        headers=_auth(admin_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == member_id
    assert body["roleId"] == ADMIN_ROLE_ID
    assert body["role"] == {
        "id": ADMIN_ROLE_ID,
        "title": "Administrator",
        "status": "active",
    }


async def test_admin_assigns_custom_active_role(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]
    async with session_factory() as db:
        db.add(Role(id="rol_engineer", title="Engineer", description=None, status="active"))
        await db.commit()

    response = await client.patch(
        f"/api/v1/users/{member_id}/role",
        json={"roleId": "rol_engineer"},
        headers=_auth(admin_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["roleId"] == "rol_engineer"
    assert body["role"] == {"id": "rol_engineer", "title": "Engineer", "status": "active"}

    filtered = await client.get(
        "/api/v1/users", params={"roleId": "rol_engineer"}, headers=_auth(admin_token)
    )
    assert [user["id"] for user in filtered.json()] == [member_id]


async def test_update_role_without_role_id_returns_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{member_id}/role",
        json={},
        headers=_auth(admin_token),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_member_cannot_change_role(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_id = await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_token = member.json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{admin_id}/role",
        json={"roleId": MEMBER_ROLE_ID},
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
        json={"roleId": MEMBER_ROLE_ID},
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
        json={"roleId": MEMBER_ROLE_ID},
        headers=_auth(admin1_token),
    )

    assert response.status_code == 200
    assert response.json()["roleId"] == MEMBER_ROLE_ID


async def test_update_role_unknown_user_returns_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/role",
        json={"roleId": ADMIN_ROLE_ID},
        headers=_auth(admin_token),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_update_role_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/users/some-id/role",
        json={"roleId": ADMIN_ROLE_ID},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_update_role_unknown_role_returns_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]

    response = await client.patch(
        f"/api/v1/users/{member_id}/role",
        json={"roleId": "rol_missing"},
        headers=_auth(admin_token),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_update_role_inactive_role_returns_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_admin(session_factory)
    member = await _register(client, name="Ada Lovelace", email="ada@example.com")
    member_id = member.json()["user"]["id"]
    admin_token = (await _login(client, email="admin@example.com")).json()["accessToken"]
    async with session_factory() as db:
        db.add(
            Role(
                id="rol_retired",
                title="Retired",
                description=None,
                status="inactive",
            )
        )
        await db.commit()

    response = await client.patch(
        f"/api/v1/users/{member_id}/role",
        json={"roleId": "rol_retired"},
        headers=_auth(admin_token),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_missing_role_row_degrades_user_response(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _create_user(
        session_factory,
        name="Ghost",
        email="ghost@example.com",
        role_id="rol_ghost",
    )

    response = await _login(client, email="ghost@example.com")

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["roleId"] == "rol_ghost"
    assert user["role"] == {"id": "rol_ghost", "title": "rol_ghost", "status": "active"}


async def test_role_title_and_status_change_reflect_in_next_user_response(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    registered = await _register(client, name="Ada Lovelace", email="ada@example.com")
    token = registered.json()["accessToken"]

    async with session_factory() as db:
        role = await db.get(Role, MEMBER_ROLE_ID)
        assert role is not None
        role.title = "Associate"
        role.status = "inactive"
        await db.commit()

    response = await client.get("/api/v1/users/me", headers=_auth(token))
    listed = await client.get(
        "/api/v1/users", params={"q": "ada@example.com"}, headers=_auth(token)
    )

    expected_role = {
        "id": MEMBER_ROLE_ID,
        "title": "Associate",
        "status": "inactive",
    }
    assert response.status_code == 200
    assert response.json()["role"] == expected_role
    assert listed.status_code == 200
    assert listed.json()[0]["role"] == expected_role


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
