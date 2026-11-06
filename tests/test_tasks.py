"""Task creation and single-get tests: POST /tasks, GET /tasks/{id}."""

from typing import Any

import pytest
from httpx import AsyncClient

_PASSWORD = "correct horse battery staple"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def _create(
    client: AsyncClient,
    *,
    token: str,
    json: dict[str, Any],
) -> Any:
    return client.post("/api/v1/tasks", json=json, headers=_auth(token))


async def test_create_task_defaults_to_todo(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await _create(client, token=token, json={"title": "Write tests"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "title",
        "description",
        "status",
        "priority",
        "assigneeId",
        "dueDate",
        "createdAt",
        "updatedAt",
    }
    assert body["title"] == "Write tests"
    assert body["status"] == "todo"
    assert body["description"] is None
    assert body["priority"] is None
    assert body["assigneeId"] is None
    assert body["dueDate"] is None
    assert body["id"]
    assert body["createdAt"]
    assert body["updatedAt"]


async def test_create_task_accepts_optional_fields(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client, email="creator@example.com")
    _, assignee_id = await _token_and_user(client, email="assignee@example.com", name="Assignee")

    response = await _create(
        client,
        token=token,
        json={
            "title": "Ship it",
            "description": "Deploy the release",
            "status": "in-progress",
            "priority": "high",
            "assigneeId": assignee_id,
            "dueDate": "2026-12-31",
        },
    )

    assert response.status_code == 201
    task = response.json()
    assert task["description"] == "Deploy the release"
    assert task["status"] == "in-progress"
    assert task["priority"] == "high"
    assert task["assigneeId"] == assignee_id
    assert task["dueDate"] == "2026-12-31"


async def test_create_task_with_done_status_returns_400(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await _create(
        client,
        token=token,
        json={"title": "Already finished", "status": "done"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_create_task_with_unknown_assignee_returns_400(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await _create(
        client,
        token=token,
        json={
            "title": "No such assignee",
            "assigneeId": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize("status", ["todo", "in-progress", "blocked"])
async def test_create_task_allows_non_done_statuses(client: AsyncClient, status: str) -> None:
    token, _ = await _token_and_user(client)

    response = await _create(
        client,
        token=token,
        json={"title": "A task", "status": status},
    )

    assert response.status_code == 201
    assert response.json()["status"] == status


async def test_create_task_requires_title(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await _create(client, token=token, json={})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_create_task_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tasks", json={"title": "A task"})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_get_task_returns_task(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)
    created = await _create(client, token=token, json={"title": "Fetch me"})
    task_id = created.json()["id"]

    response = await client.get(f"/api/v1/tasks/{task_id}", headers=_auth(token))

    assert response.status_code == 200
    assert response.json() == created.json()


async def test_get_task_unknown_id_returns_404(client: AsyncClient) -> None:
    token, _ = await _token_and_user(client)

    response = await client.get(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_get_task_without_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/some-id")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
