"""Live events tests: SSE auth/validation plus mutation fan-out on resources/tasks."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from httpx import AsyncClient

from app.api.v1.endpoints.events import _event_stream
from app.core.events import TASKS_CHANNEL, LiveEvent, encode_live_event, live_event_bus
from tests.helpers import PASSWORD, auth

_CHANNEL_QUERY = "channel=resources%2Ftasks"


@contextmanager
def _subscribed(channel: str = TASKS_CHANNEL) -> Iterator[asyncio.Queue[LiveEvent]]:
    """Subscribe the test to ``channel`` and always unsubscribe afterwards."""
    queue = live_event_bus.subscribe(channel)
    try:
        yield queue
    finally:
        live_event_bus.unsubscribe(channel, queue)


async def _register(client: AsyncClient) -> tuple[str, str]:
    """Register a Member and return (access token, user id)."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": "ada@example.com", "password": PASSWORD},
    )
    body = response.json()
    return body["accessToken"], body["user"]["id"]


async def _create_task(client: AsyncClient, token: str, assignee_id: str) -> str:
    """Create a task assigned to the caller and return its id."""
    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Live task", "assigneeId": assignee_id},
        headers=auth(token),
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_events_requires_access_token(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/events?{_CHANNEL_QUERY}")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_events_rejects_invalid_access_token(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/events?{_CHANNEL_QUERY}&access_token=not-a-jwt")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_events_rejects_unknown_channel(client: AsyncClient) -> None:
    token, _ = await _register(client)

    response = await client.get(
        "/api/v1/events", params={"channel": "resources/users", "access_token": token}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_create_task_publishes_created_event(client: AsyncClient) -> None:
    token, user_id = await _register(client)
    with _subscribed() as queue:
        task_id = await _create_task(client, token, user_id)

    event = queue.get_nowait()
    assert event.channel == TASKS_CHANNEL
    assert event.type == "created"
    assert event.ids == (task_id,)


async def test_update_task_publishes_updated_event(client: AsyncClient) -> None:
    token, user_id = await _register(client)
    task_id = await _create_task(client, token, user_id)

    with _subscribed() as queue:
        response = await client.patch(
            f"/api/v1/tasks/{task_id}",
            json={"priority": "high"},
            headers=auth(token),
        )

    assert response.status_code == 200
    event = queue.get_nowait()
    assert event.type == "updated"
    assert event.ids == (task_id,)


async def test_delete_task_publishes_deleted_event(client: AsyncClient) -> None:
    token, user_id = await _register(client)
    task_id = await _create_task(client, token, user_id)

    with _subscribed() as queue:
        response = await client.delete(f"/api/v1/tasks/{task_id}", headers=auth(token))

    assert response.status_code == 204
    event = queue.get_nowait()
    assert event.type == "deleted"
    assert event.ids == (task_id,)


async def test_bulk_update_publishes_one_event_with_updated_ids(client: AsyncClient) -> None:
    token, user_id = await _register(client)
    first_id = await _create_task(client, token, user_id)
    second_id = await _create_task(client, token, user_id)

    with _subscribed() as queue:
        response = await client.patch(
            "/api/v1/tasks/bulk",
            json={"ids": [first_id, second_id], "priority": "high"},
            headers=auth(token),
        )

    assert response.status_code == 200
    assert response.json()["updated"] == 2
    event = queue.get_nowait()
    assert event.type == "updated"
    assert set(event.ids) == {first_id, second_id}
    assert queue.empty()


async def test_event_stream_emits_connected_comment_then_live_event() -> None:
    event = LiveEvent(
        channel=TASKS_CHANNEL,
        type="updated",
        ids=("task-1", "task-2"),
        date=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    stream = _event_stream(TASKS_CHANNEL)
    try:
        assert await anext(stream) == b": connected\n\n"

        live_event_bus.publish(event)
        frame = await asyncio.wait_for(anext(stream), timeout=1)
    finally:
        await stream.aclose()

    assert frame == encode_live_event(event)
    event_name, data_line = frame.decode().split("\n")[:2]
    assert event_name == "event: live"
    assert json.loads(data_line.removeprefix("data: ")) == {
        "channel": TASKS_CHANNEL,
        "type": "updated",
        "payload": {"ids": ["task-1", "task-2"]},
        "date": "2026-01-02T03:04:05+00:00",
    }
