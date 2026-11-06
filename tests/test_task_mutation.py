"""Task mutation tests: PATCH /tasks/{id}, DELETE /tasks/{id}."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.user import Role, User

_PASSWORD = "correct horse battery staple"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(
    client: AsyncClient,
    *,
    email: str,
    name: str = "Member",
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": _PASSWORD},
    )
    return response.json()


async def _login(client: AsyncClient, *, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    return response.json()["accessToken"]


async def _create_admin(
    factory: async_sessionmaker[AsyncSession],
    *,
    email: str = "admin@example.com",
) -> str:
    """Seed an admin directly (admins are born via seed, not /register)."""
    user = User(
        name="Admin",
        email=email,
        hashed_password=hash_password(_PASSWORD),
        role=Role.ADMIN.value,
    )
    async with factory() as db:
        db.add(user)
        await db.commit()
        return user.id


async def _create_task(
    client: AsyncClient,
    *,
    token: str,
    assignee_id: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    json: dict[str, Any] = {"title": "A task", **fields}
    if assignee_id is not None:
        json["assigneeId"] = assignee_id
    response = await client.post("/api/v1/tasks", json=json, headers=_auth(token))
    return response.json()


def _patch(client: AsyncClient, *, token: str, task_id: str, json: dict[str, Any]) -> Any:
    return client.patch(f"/api/v1/tasks/{task_id}", json=json, headers=_auth(token))


def _delete(client: AsyncClient, *, token: str, task_id: str) -> Any:
    return client.delete(f"/api/v1/tasks/{task_id}", headers=_auth(token))


async def test_assignee_can_patch_own_task(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    response = await _patch(client, token=token, task_id=task["id"], json={"title": "Renamed"})

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert response.json()["id"] == task["id"]


async def test_member_cannot_patch_others_task(
    client: AsyncClient,
) -> None:
    assignee = await _register(client, email="assignee@example.com")
    other = await _register(client, email="other@example.com")
    task = await _create_task(
        client, token=assignee["accessToken"], assignee_id=assignee["user"]["id"]
    )

    response = await _patch(
        client, token=other["accessToken"], task_id=task["id"], json={"title": "Mine"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_admin_can_patch_any_task(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    member = await _register(client, email="ada@example.com")
    task = await _create_task(client, token=member["accessToken"], assignee_id=member["user"]["id"])
    await _create_admin(session_factory)
    admin_token = await _login(client, email="admin@example.com")

    response = await _patch(
        client, token=admin_token, task_id=task["id"], json={"title": "Admin edit"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Admin edit"


async def test_omitted_fields_are_unchanged(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(
        client,
        token=token,
        assignee_id=member["user"]["id"],
        description="Keep me",
        priority="high",
        dueDate="2026-12-31",
    )

    response = await _patch(client, token=token, task_id=task["id"], json={"title": "New title"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New title"
    assert body["description"] == "Keep me"
    assert body["priority"] == "high"
    assert body["assigneeId"] == member["user"]["id"]
    assert body["dueDate"] == "2026-12-31"


async def test_explicit_null_clears_optional_fields(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(
        client,
        token=token,
        assignee_id=member["user"]["id"],
        description="Clear me",
        priority="medium",
        dueDate="2026-12-31",
    )

    response = await _patch(
        client,
        token=token,
        task_id=task["id"],
        json={"description": None, "priority": None, "assigneeId": None, "dueDate": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] is None
    assert body["priority"] is None
    assert body["assigneeId"] is None
    assert body["dueDate"] is None


async def test_patch_null_title_is_rejected(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    response = await _patch(client, token=token, task_id=task["id"], json={"title": None})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_patch_null_status_is_rejected(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    response = await _patch(client, token=token, task_id=task["id"], json={"status": None})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_status_advances_todo_to_in_progress_to_done(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    first = await _patch(client, token=token, task_id=task["id"], json={"status": "in-progress"})
    second = await _patch(client, token=token, task_id=task["id"], json={"status": "done"})

    assert first.status_code == 200
    assert first.json()["status"] == "in-progress"
    assert second.status_code == 200
    assert second.json()["status"] == "done"


async def test_status_todo_to_done_is_rejected(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    response = await _patch(client, token=token, task_id=task["id"], json={"status": "done"})

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_status_in_progress_to_todo_is_rejected(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])
    await _patch(client, token=token, task_id=task["id"], json={"status": "in-progress"})

    response = await _patch(client, token=token, task_id=task["id"], json={"status": "todo"})

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_status_blocked_from_todo_then_unblock_returns_to_todo(
    client: AsyncClient,
) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    blocked = await _patch(client, token=token, task_id=task["id"], json={"status": "blocked"})
    unblocked = await _patch(client, token=token, task_id=task["id"], json={"status": "todo"})

    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert unblocked.status_code == 200
    assert unblocked.json()["status"] == "todo"


async def test_unblock_returns_to_prior_state_not_requested_state(
    client: AsyncClient,
) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])
    await _patch(client, token=token, task_id=task["id"], json={"status": "in-progress"})
    await _patch(client, token=token, task_id=task["id"], json={"status": "blocked"})

    unblocked = await _patch(client, token=token, task_id=task["id"], json={"status": "todo"})

    assert unblocked.status_code == 200
    assert unblocked.json()["status"] == "in-progress"


async def test_born_blocked_task_unblocks_to_todo(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(
        client,
        token=token,
        assignee_id=member["user"]["id"],
        status="blocked",
    )

    unblocked = await _patch(client, token=token, task_id=task["id"], json={"status": "todo"})

    assert unblocked.status_code == 200
    assert unblocked.json()["status"] == "todo"


async def test_status_done_cannot_be_blocked(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])
    await _patch(client, token=token, task_id=task["id"], json={"status": "in-progress"})
    await _patch(client, token=token, task_id=task["id"], json={"status": "done"})

    response = await _patch(client, token=token, task_id=task["id"], json={"status": "blocked"})

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_status_done_is_terminal(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])
    await _patch(client, token=token, task_id=task["id"], json={"status": "in-progress"})
    await _patch(client, token=token, task_id=task["id"], json={"status": "done"})

    response = await _patch(client, token=token, task_id=task["id"], json={"status": "in-progress"})

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_status_blocked_to_done_is_rejected(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])
    await _patch(client, token=token, task_id=task["id"], json={"status": "blocked"})

    response = await _patch(client, token=token, task_id=task["id"], json={"status": "done"})

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_member_cannot_acquire_others_task_by_assigning_self(
    client: AsyncClient,
) -> None:
    assignee = await _register(client, email="assignee@example.com")
    other = await _register(client, email="other@example.com")
    task = await _create_task(
        client, token=assignee["accessToken"], assignee_id=assignee["user"]["id"]
    )

    response = await _patch(
        client,
        token=other["accessToken"],
        task_id=task["id"],
        json={"assigneeId": other["user"]["id"]},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_patch_unknown_assignee_returns_400(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    response = await _patch(
        client,
        token=token,
        task_id=task["id"],
        json={"assigneeId": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_patch_unknown_task_returns_404(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")

    response = await _patch(
        client,
        token=member["accessToken"],
        task_id="00000000-0000-0000-0000-000000000000",
        json={"title": "Nothing"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_patch_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/tasks/some-id",
        json={"title": "No auth"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_assignee_can_delete_own_task(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    response = await _delete(client, token=token, task_id=task["id"])

    assert response.status_code == 204

    after = await client.get(f"/api/v1/tasks/{task['id']}", headers=_auth(token))
    assert after.status_code == 404


async def test_member_cannot_delete_others_task(client: AsyncClient) -> None:
    assignee = await _register(client, email="assignee@example.com")
    other = await _register(client, email="other@example.com")
    task = await _create_task(
        client, token=assignee["accessToken"], assignee_id=assignee["user"]["id"]
    )

    response = await _delete(client, token=other["accessToken"], task_id=task["id"])

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_admin_can_delete_any_task(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    member = await _register(client, email="ada@example.com")
    task = await _create_task(client, token=member["accessToken"], assignee_id=member["user"]["id"])
    await _create_admin(session_factory)
    admin_token = await _login(client, email="admin@example.com")

    response = await _delete(client, token=admin_token, task_id=task["id"])

    assert response.status_code == 204


async def test_delete_unknown_task_returns_404(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")

    response = await _delete(
        client,
        token=member["accessToken"],
        task_id="00000000-0000-0000-0000-000000000000",
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_delete_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.delete("/api/v1/tasks/some-id")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
