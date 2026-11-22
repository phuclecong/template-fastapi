"""Dashboard summary tests: GET /dashboard/summary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.role import MEMBER_ROLE_ID
from app.models.task import Priority, Status, Task
from app.models.user import User
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


async def _seed_user(
    factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    email: str,
    user_id: str | None = None,
) -> str:
    """Insert a Member directly so an assignee with a chosen id can be seeded."""
    user = User(
        id=user_id or f"user-{email.split('@')[0]}",
        name=name,
        email=email,
        hashed_password=hash_password(_PASSWORD),
        role_id=MEMBER_ROLE_ID,
    )
    async with factory() as db:
        db.add(user)
        await db.commit()
        return user.id


async def _seed_task(
    factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    status: str = Status.TODO.value,
    priority: str | None = None,
    assignee_id: str | None = None,
    due_date: datetime | None = None,
) -> str:
    """Insert a task directly; ``done`` tasks have no HTTP birth path."""
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


async def _summary(client: AsyncClient, token: str) -> dict[str, Any]:
    response = await client.get("/api/v1/dashboard/summary", headers=_auth(token))
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _parsed_instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def test_summary_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/summary")

    assert response.status_code == 401


async def test_totals_count_open_and_overdue_only_for_unfinished_tasks(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, _ = await _token_and_user(client)
    now = datetime.now(UTC)
    await _seed_task(
        session_factory,
        title="overdue open",
        status=Status.TODO.value,
        due_date=now - timedelta(minutes=1),
    )
    await _seed_task(
        session_factory,
        title="overdue but done",
        status=Status.DONE.value,
        due_date=now - timedelta(minutes=1),
    )
    await _seed_task(
        session_factory,
        title="not yet due",
        status=Status.IN_PROGRESS.value,
        due_date=now + timedelta(minutes=1),
    )
    await _seed_task(
        session_factory,
        title="no due date",
        status=Status.BLOCKED.value,
    )
    await _seed_task(
        session_factory,
        title="done on time",
        status=Status.DONE.value,
        due_date=now + timedelta(days=1),
    )

    body = await _summary(client, token)

    assert body["totals"] == {
        "total": 5,
        "open": 3,
        "overdue": 1,
        "completionRate": 0.4,
    }


async def test_by_status_lists_every_status_zero_filled_in_contract_order(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, _ = await _token_and_user(client)
    for status, count in (
        (Status.TODO.value, 2),
        (Status.IN_PROGRESS.value, 1),
        (Status.DONE.value, 3),
        (Status.BLOCKED.value, 1),
    ):
        for index in range(count):
            await _seed_task(session_factory, title=f"{status}-{index}", status=status)

    body = await _summary(client, token)

    assert body["byStatus"] == [
        {"status": "todo", "count": 2},
        {"status": "in-progress", "count": 1},
        {"status": "done", "count": 3},
        {"status": "blocked", "count": 1},
    ]


async def test_by_priority_zero_fills_and_groups_null_as_unassigned(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, _ = await _token_and_user(client)
    for priority, count in (
        (Priority.LOW.value, 2),
        (Priority.MEDIUM.value, 0),
        (Priority.HIGH.value, 3),
        (None, 2),
    ):
        for index in range(count):
            await _seed_task(session_factory, title=f"{priority}-{index}", priority=priority)

    body = await _summary(client, token)

    assert body["byPriority"] == [
        {"priority": "low", "count": 2},
        {"priority": "medium", "count": 0},
        {"priority": "high", "count": 3},
        {"priority": "unassigned", "count": 2},
    ]


async def test_by_assignee_lists_five_busiest_then_appends_unassigned(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, _ = await _token_and_user(client)
    workloads = (
        ("Ava", 4),
        ("Ben", 3),
        ("Cara", 2),
        ("Dan", 2),
        ("Eve", 1),
        ("Fay", 1),
    )
    for name, count in workloads:
        assignee_id = await _seed_user(
            session_factory,
            name=name,
            email=f"{name.lower()}@example.com",
        )
        for index in range(count):
            await _seed_task(
                session_factory,
                title=f"{name}-{index}",
                assignee_id=assignee_id,
            )
    for index in range(10):
        await _seed_task(session_factory, title=f"unassigned-{index}")

    body = await _summary(client, token)

    # Five busiest only: Eve edges out Fay on the name tie-break. Unassigned is
    # appended last even though its count is the largest.
    assert body["byAssignee"] == [
        {"assigneeId": "user-ava", "name": "Ava", "count": 4},
        {"assigneeId": "user-ben", "name": "Ben", "count": 3},
        {"assigneeId": "user-cara", "name": "Cara", "count": 2},
        {"assigneeId": "user-dan", "name": "Dan", "count": 2},
        {"assigneeId": "user-eve", "name": "Eve", "count": 1},
        {"assigneeId": None, "name": "", "count": 10},
    ]
    assert body["totals"]["total"] == 23


async def test_by_assignee_breaks_ties_by_name_then_id(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, _ = await _token_and_user(client)
    sam_b = await _seed_user(
        session_factory, name="Sam", email="sam.b@example.com", user_id="user-sam-b"
    )
    sam_a = await _seed_user(
        session_factory, name="Sam", email="sam.a@example.com", user_id="user-sam-a"
    )
    zed = await _seed_user(session_factory, name="Zed", email="zed@example.com")
    for assignee_id in (sam_b, sam_a, zed):
        for index in range(2):
            await _seed_task(
                session_factory,
                title=f"{assignee_id}-{index}",
                assignee_id=assignee_id,
            )

    body = await _summary(client, token)

    assert [entry["assigneeId"] for entry in body["byAssignee"]] == [
        "user-sam-a",
        "user-sam-b",
        zed,
    ]


async def test_by_assignee_omits_unassigned_bucket_when_no_task_is_unassigned(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, _ = await _token_and_user(client)
    assignee_id = await _seed_user(session_factory, name="Ava", email="ava@example.com")
    await _seed_task(session_factory, title="assigned", assignee_id=assignee_id)

    body = await _summary(client, token)

    assert body["byAssignee"] == [{"assigneeId": assignee_id, "name": "Ava", "count": 1}]


async def test_empty_board_returns_zero_filled_summary(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    body = await _summary(client, token)

    assert body["totals"] == {"total": 0, "open": 0, "overdue": 0, "completionRate": 0}
    assert body["byStatus"] == [
        {"status": status, "count": 0} for status in ("todo", "in-progress", "done", "blocked")
    ]
    assert body["byPriority"] == [
        {"priority": priority, "count": 0} for priority in ("low", "medium", "high", "unassigned")
    ]
    assert body["byAssignee"] == []

    generated_at = _parsed_instant(body["generatedAt"])
    assert generated_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - generated_at) < timedelta(minutes=1)
