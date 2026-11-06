"""Task bulk-update tests: PATCH /tasks/bulk."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.task import Status, Task
from app.models.user import Role, User

_PASSWORD = "correct horse battery staple"

_FORBIDDEN_REASON = "You do not have permission to perform this action."
_NOT_FOUND_REASON = "No task exists with this id."
_INVALID_STATUS_REASON = "Invalid status transition."


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


async def _seed_done_task(
    factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    assignee_id: str,
) -> str:
    """Seed a ``done`` task directly; there is no HTTP birth path for ``done``."""
    task = Task(title=title, status=Status.DONE.value, assignee_id=assignee_id)
    async with factory() as db:
        db.add(task)
        await db.commit()
        return task.id


def _bulk(client: AsyncClient, *, token: str, json: dict[str, Any]) -> Any:
    return client.patch("/api/v1/tasks/bulk", json=json, headers=_auth(token))


async def test_bulk_updates_status_priority_assignee_across_ids(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    other = await _register(client, email="bob@example.com")
    token = member["accessToken"]
    first = await _create_task(client, token=token, assignee_id=member["user"]["id"])
    second = await _create_task(client, token=token, assignee_id=member["user"]["id"])

    response = await _bulk(
        client,
        token=token,
        json={
            "ids": [first["id"], second["id"]],
            "status": "in-progress",
            "priority": "high",
            "assigneeId": other["user"]["id"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 2, "failed": []}

    for task_id in (first["id"], second["id"]):
        after = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(token))
        body = after.json()
        assert body["status"] == "in-progress"
        assert body["priority"] == "high"
        assert body["assigneeId"] == other["user"]["id"]


async def test_member_mixed_batch_updates_own_and_fails_others(client: AsyncClient) -> None:
    assignee = await _register(client, email="assignee@example.com")
    other = await _register(client, email="other@example.com")
    own = await _create_task(
        client, token=assignee["accessToken"], assignee_id=assignee["user"]["id"]
    )
    theirs = await _create_task(client, token=other["accessToken"], assignee_id=other["user"]["id"])

    response = await _bulk(
        client,
        token=assignee["accessToken"],
        json={"ids": [own["id"], theirs["id"]], "status": "in-progress"},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert response.json()["failed"] == [{"id": theirs["id"], "reason": _FORBIDDEN_REASON}]

    own_after = await client.get(
        f"/api/v1/tasks/{own['id']}", headers=_auth(assignee["accessToken"])
    )
    theirs_after = await client.get(
        f"/api/v1/tasks/{theirs['id']}", headers=_auth(other["accessToken"])
    )
    assert own_after.json()["status"] == "in-progress"
    assert theirs_after.json()["status"] == "todo"


async def test_bulk_reports_not_found_for_unknown_id(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    task = await _create_task(client, token=member["accessToken"], assignee_id=member["user"]["id"])
    unknown = "00000000-0000-0000-0000-000000000000"

    response = await _bulk(
        client,
        token=member["accessToken"],
        json={"ids": [task["id"], unknown], "status": "in-progress"},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert response.json()["failed"] == [{"id": unknown, "reason": _NOT_FOUND_REASON}]


async def test_bulk_reports_invalid_status_transition_per_id(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    todo = await _create_task(client, token=token, assignee_id=member["user"]["id"])
    done = await _seed_done_task(
        session_factory, title="Finished", assignee_id=member["user"]["id"]
    )

    response = await _bulk(
        client,
        token=token,
        json={"ids": [todo["id"], done], "status": "in-progress"},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert response.json()["failed"] == [{"id": done, "reason": _INVALID_STATUS_REASON}]

    todo_after = await client.get(f"/api/v1/tasks/{todo['id']}", headers=_auth(token))
    done_after = await client.get(f"/api/v1/tasks/{done}", headers=_auth(token))
    assert todo_after.json()["status"] == "in-progress"
    assert done_after.json()["status"] == "done"


async def test_bulk_requires_at_least_one_update_field(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    task = await _create_task(client, token=member["accessToken"], assignee_id=member["user"]["id"])

    response = await _bulk(
        client,
        token=member["accessToken"],
        json={"ids": [task["id"]]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_bulk_rejects_empty_ids(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")

    response = await _bulk(
        client,
        token=member["accessToken"],
        json={"ids": [], "status": "in-progress"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_bulk_rejects_null_status(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    task = await _create_task(client, token=member["accessToken"], assignee_id=member["user"]["id"])

    response = await _bulk(
        client,
        token=member["accessToken"],
        json={"ids": [task["id"]], "status": None},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_bulk_unknown_assignee_returns_400(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    task = await _create_task(client, token=member["accessToken"], assignee_id=member["user"]["id"])

    response = await _bulk(
        client,
        token=member["accessToken"],
        json={"ids": [task["id"]], "assigneeId": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_bulk_unknown_assignee_on_others_tasks_reports_forbidden_not_400(
    client: AsyncClient,
) -> None:
    other = await _register(client, email="other@example.com")
    theirs = await _create_task(client, token=other["accessToken"], assignee_id=other["user"]["id"])
    member = await _register(client, email="member@example.com")

    response = await _bulk(
        client,
        token=member["accessToken"],
        json={
            "ids": [theirs["id"]],
            "assigneeId": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "updated": 0,
        "failed": [{"id": theirs["id"], "reason": _FORBIDDEN_REASON}],
    }


async def test_bulk_null_clears_priority_and_assignee(client: AsyncClient) -> None:
    member = await _register(client, email="ada@example.com")
    token = member["accessToken"]
    task = await _create_task(
        client,
        token=token,
        assignee_id=member["user"]["id"],
        priority="high",
    )

    response = await _bulk(
        client,
        token=token,
        json={"ids": [task["id"]], "priority": None, "assigneeId": None},
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 1, "failed": []}

    after = await client.get(f"/api/v1/tasks/{task['id']}", headers=_auth(token))
    assert after.json()["priority"] is None
    assert after.json()["assigneeId"] is None


async def test_admin_can_bulk_update_any_task(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first_member = await _register(client, email="first@example.com")
    second_member = await _register(client, email="second@example.com")
    first = await _create_task(
        client, token=first_member["accessToken"], assignee_id=first_member["user"]["id"]
    )
    second = await _create_task(
        client, token=second_member["accessToken"], assignee_id=second_member["user"]["id"]
    )
    await _create_admin(session_factory)
    admin_token = await _login(client, email="admin@example.com")

    response = await _bulk(
        client,
        token=admin_token,
        json={"ids": [first["id"], second["id"]], "status": "blocked"},
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 2, "failed": []}

    for task_id in (first["id"], second["id"]):
        after = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(admin_token))
        assert after.json()["status"] == "blocked"


async def test_bulk_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/tasks/bulk",
        json={"ids": ["some-id"], "status": "in-progress"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
