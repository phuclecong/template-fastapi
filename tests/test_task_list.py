"""Task list tests: GET /tasks with filtering, sorting, and pagination."""

from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.task import Priority, Status, Task
from tests.helpers import PASSWORD as _PASSWORD
from tests.helpers import auth as _auth


async def _token_and_user(
    client: AsyncClient,
    *,
    email: str = "ada@example.com",
    name: str = "Ada Lovelace",
) -> tuple[str, str]:
    """Register a fresh user and return (access token, user id)."""
    registered = await client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": _PASSWORD},
    )
    body = registered.json()
    return body["accessToken"], body["user"]["id"]


def _create(client: AsyncClient, *, token: str, json: dict[str, Any]) -> Any:
    return client.post("/api/v1/tasks", json=json, headers=_auth(token))


async def _seed_task(
    factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    status: str = Status.TODO.value,
    priority: str | None = None,
    assignee_id: str | None = None,
    due_date: datetime | None = None,
) -> str:
    """Insert a task directly; the only way to seed a ``done`` task (no HTTP birth path)."""
    task = Task(
        title=title,
        status=status,
        priority=priority,
        assignee_id=assignee_id,
        due_date=due_date,
    )
    async with factory() as db:
        db.add(task)
        await db.commit()
        return task.id


async def test_list_returns_all_tasks_with_total_count(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    for title in ("First", "Second", "Third"):
        assert (await _create(client, token=token, json={"title": title})).status_code == 201

    response = await client.get("/api/v1/tasks", headers=_auth(token))

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    assert {task["title"] for task in response.json()} == {"First", "Second", "Third"}


async def test_list_filters_by_q_case_insensitively(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    for title in ("Write tests", "Ship feature", "Ship tests"):
        await _create(client, token=token, json={"title": title})

    response = await client.get("/api/v1/tasks", params={"q": "ship"}, headers=_auth(token))

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    assert {task["title"] for task in response.json()} == {"Ship feature", "Ship tests"}


async def test_list_filters_by_status(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(client, token=token, json={"title": "Todo task"})
    await _create(client, token=token, json={"title": "Doing task", "status": "in-progress"})

    response = await client.get(
        "/api/v1/tasks", params={"status": "in-progress"}, headers=_auth(token)
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert [task["title"] for task in response.json()] == ["Doing task"]


async def test_list_filters_by_multiple_statuses(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(client, token=token, json={"title": "Todo task"})
    await _create(client, token=token, json={"title": "Doing task", "status": "in-progress"})
    await _create(client, token=token, json={"title": "Blocked task", "status": "blocked"})

    response = await client.get(
        "/api/v1/tasks",
        params=[("status", "todo"), ("status", "in-progress")],
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    assert {task["title"] for task in response.json()} == {"Todo task", "Doing task"}


async def test_list_filters_by_priority(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(client, token=token, json={"title": "Urgent", "priority": "high"})
    await _create(client, token=token, json={"title": "Relaxed", "priority": "low"})

    response = await client.get("/api/v1/tasks", params={"priority": "high"}, headers=_auth(token))

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert [task["title"] for task in response.json()] == ["Urgent"]


async def test_list_filters_by_multiple_priorities(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(client, token=token, json={"title": "Urgent", "priority": "high"})
    await _create(client, token=token, json={"title": "Calm", "priority": "low"})
    await _create(client, token=token, json={"title": "Medium", "priority": "medium"})

    response = await client.get(
        "/api/v1/tasks",
        params=[("priority", "high"), ("priority", "medium")],
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    assert {task["title"] for task in response.json()} == {"Urgent", "Medium"}


async def test_list_filters_by_assignee(client: AsyncClient) -> None:
    token, creator_id = await _token_and_user(client)
    _, assignee_id = await _token_and_user(client, email="assignee@example.com", name="Assignee")
    await _create(client, token=token, json={"title": "Assigned", "assigneeId": assignee_id})
    await _create(client, token=token, json={"title": "Mine", "assigneeId": creator_id})
    await _create(client, token=token, json={"title": "Free"})

    assigned = await client.get(
        "/api/v1/tasks", params={"assigneeId": assignee_id}, headers=_auth(token)
    )
    unassigned = await client.get(
        "/api/v1/tasks", params={"assigneeId": "unassigned"}, headers=_auth(token)
    )

    assert assigned.status_code == 200
    assert [task["title"] for task in assigned.json()] == ["Assigned"]
    assert unassigned.status_code == 200
    assert [task["title"] for task in unassigned.json()] == ["Free"]


async def test_list_filters_by_multiple_assignees_and_unassigned(client: AsyncClient) -> None:
    token, creator_id = await _token_and_user(client)
    _, assignee_id = await _token_and_user(client, email="assignee@example.com", name="Assignee")
    await _create(client, token=token, json={"title": "Assigned", "assigneeId": assignee_id})
    await _create(client, token=token, json={"title": "Mine", "assigneeId": creator_id})
    await _create(client, token=token, json={"title": "Free"})

    response = await client.get(
        "/api/v1/tasks",
        params=[("assigneeId", assignee_id), ("assigneeId", "unassigned")],
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    assert {task["title"] for task in response.json()} == {"Assigned", "Free"}


async def test_list_rejects_unknown_assignee(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(client, token=token, json={"title": "A task"})

    response = await client.get(
        "/api/v1/tasks",
        params={"assigneeId": "00000000-0000-0000-0000-000000000000"},
        headers=_auth(token),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_list_combines_filters_with_and(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(
        client, token=token, json={"title": "Match A", "status": "in-progress", "priority": "high"}
    )
    await _create(
        client, token=token, json={"title": "Match B", "status": "in-progress", "priority": "high"}
    )
    await _create(client, token=token, json={"title": "Wrong status", "priority": "high"})
    await _create(
        client,
        token=token,
        json={"title": "Wrong priority", "status": "in-progress", "priority": "low"},
    )

    response = await client.get(
        "/api/v1/tasks",
        params={"status": "in-progress", "priority": "high"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    assert {task["title"] for task in response.json()} == {"Match A", "Match B"}


async def test_list_ignores_empty_filter_repeats(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(client, token=token, json={"title": "Todo task"})
    await _create(client, token=token, json={"title": "Urgent", "priority": "high"})
    await _create(client, token=token, json={"title": "Free"})

    response = await client.get(
        "/api/v1/tasks",
        params=[("status", ""), ("priority", ""), ("assigneeId", "")],
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"


async def test_list_filters_by_due_date_range(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    await _create(
        client, token=token, json={"title": "Early", "dueDate": "2026-01-01T09:00:00+00:00"}
    )
    await _create(
        client, token=token, json={"title": "Mid", "dueDate": "2026-06-15T12:00:00+00:00"}
    )
    await _create(
        client, token=token, json={"title": "Late", "dueDate": "2026-12-31T23:59:59+00:00"}
    )
    await _create(client, token=token, json={"title": "No date"})

    response = await client.get(
        "/api/v1/tasks",
        params={
            "dueDate_gte": "2026-06-15T12:00:00+00:00",
            "dueDate_lte": "2026-12-31T23:59:59+00:00",
        },
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    assert {task["title"] for task in response.json()} == {"Mid", "Late"}


async def test_list_rejects_date_only_due_date_bounds(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    for field in ("dueDate_gte", "dueDate_lte"):
        response = await client.get(
            "/api/v1/tasks", params={field: "2026-06-15"}, headers=_auth(token)
        )

        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"


async def test_list_rejects_offset_less_due_date_bounds(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    for field in ("dueDate_gte", "dueDate_lte"):
        response = await client.get(
            "/api/v1/tasks",
            params={field: "2026-06-15T12:00:00"},
            headers=_auth(token),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"


async def test_list_paginates_with_start_and_end(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    for title in ("A", "B", "C", "D"):
        await _create(client, token=token, json={"title": title})

    response = await client.get(
        "/api/v1/tasks", params={"_start": 1, "_end": 3}, headers=_auth(token)
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "4"
    assert [task["title"] for task in response.json()] == ["B", "C"]


async def test_list_sorts_by_title_desc(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    for title in ("Beta", "Alpha", "Gamma"):
        await _create(client, token=token, json={"title": title})

    response = await client.get(
        "/api/v1/tasks", params={"_sort": "title", "_order": "desc"}, headers=_auth(token)
    )

    assert [task["title"] for task in response.json()] == ["Gamma", "Beta", "Alpha"]


async def test_list_sorts_by_status_in_declared_order(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token, _ = await _token_and_user(client)
    for title, status in (
        ("Blocked", Status.BLOCKED.value),
        ("Done", Status.DONE.value),
        ("In progress", Status.IN_PROGRESS.value),
        ("Todo", Status.TODO.value),
    ):
        await _seed_task(session_factory, title=title, status=status)

    response = await client.get("/api/v1/tasks", params={"_sort": "status"}, headers=_auth(token))

    assert [task["status"] for task in response.json()] == [
        "todo",
        "in-progress",
        "done",
        "blocked",
    ]


async def test_list_sorts_by_priority_in_declared_order(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token, _ = await _token_and_user(client)
    for title, priority in (
        ("High", Priority.HIGH.value),
        ("Low", Priority.LOW.value),
        ("Medium", Priority.MEDIUM.value),
        ("None", None),
    ):
        await _seed_task(session_factory, title=title, priority=priority)

    response = await client.get("/api/v1/tasks", params={"_sort": "priority"}, headers=_auth(token))

    assert [task["title"] for task in response.json()] == ["Low", "Medium", "High", "None"]


async def test_list_sorts_by_due_date(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token, _ = await _token_and_user(client)
    for title, due in (
        ("Third", datetime(2026, 12, 31, tzinfo=UTC)),
        ("First", datetime(2026, 1, 1, tzinfo=UTC)),
        ("Second", datetime(2026, 6, 1, tzinfo=UTC)),
    ):
        await _seed_task(session_factory, title=title, due_date=due)

    response = await client.get("/api/v1/tasks", params={"_sort": "dueDate"}, headers=_auth(token))

    assert [task["title"] for task in response.json()] == ["First", "Second", "Third"]


async def test_list_sorts_due_dates_with_nulls_last_in_both_directions(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token, _ = await _token_and_user(client)
    for title, due in (
        ("Undated", None),
        ("Later", datetime(2026, 12, 31, tzinfo=UTC)),
        ("Earlier", datetime(2026, 1, 1, tzinfo=UTC)),
    ):
        await _seed_task(session_factory, title=title, due_date=due)

    ascending = await client.get("/api/v1/tasks", params={"_sort": "dueDate"}, headers=_auth(token))
    descending = await client.get(
        "/api/v1/tasks",
        params={"_sort": "dueDate", "_order": "desc"},
        headers=_auth(token),
    )

    assert [task["title"] for task in ascending.json()] == ["Earlier", "Later", "Undated"]
    assert [task["title"] for task in descending.json()] == ["Later", "Earlier", "Undated"]


async def test_list_combines_filters_with_pagination(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    for title in ("Ship A", "Ship B", "Ship C", "Write tests"):
        await _create(client, token=token, json={"title": title})

    response = await client.get(
        "/api/v1/tasks",
        params={"q": "ship", "_start": 0, "_end": 2},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    assert {task["title"] for task in response.json()} == {"Ship A", "Ship B"}


async def test_list_rejects_unknown_sort_field(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await client.get("/api/v1/tasks", params={"_sort": "bogus"}, headers=_auth(token))

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_list_rejects_invalid_order(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await client.get(
        "/api/v1/tasks", params={"_order": "sideways"}, headers=_auth(token)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_list_rejects_invalid_status(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await client.get("/api/v1/tasks", params={"status": "bogus"}, headers=_auth(token))

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_list_rejects_invalid_priority(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await client.get(
        "/api/v1/tasks", params={"priority": "urgent"}, headers=_auth(token)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_list_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
