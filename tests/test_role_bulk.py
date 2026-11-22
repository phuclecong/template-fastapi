"""Role catalogue bulk operations: PATCH /roles/bulk and POST /roles/bulk-delete."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers import (
    PASSWORD as _PASSWORD,
)
from tests.helpers import (
    admin_token as _admin_token,
)
from tests.helpers import (
    auth as _auth,
)
from tests.helpers import (
    member_token as _member_token,
)


async def _new_role(
    client: AsyncClient,
    *,
    token: str,
    title: str,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"title": title}
    if description is not None:
        payload["description"] = description
    if status is not None:
        payload["status"] = status
    response = await client.post("/api/v1/roles", json=payload, headers=_auth(token))
    assert response.status_code == 201
    return response.json()


def _bulk_update(client: AsyncClient, *, token: str, json: dict[str, Any]) -> Any:
    return client.patch("/api/v1/roles/bulk", json=json, headers=_auth(token))


def _bulk_delete(client: AsyncClient, *, token: str, json: dict[str, Any]) -> Any:
    return client.post("/api/v1/roles/bulk-delete", json=json, headers=_auth(token))


async def _get(client: AsyncClient, *, token: str, role_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/roles/{role_id}", headers=_auth(token))
    assert response.status_code == 200
    return response.json()


async def test_bulk_update_requires_authentication(client: AsyncClient) -> None:
    response = await client.patch("/api/v1/roles/bulk", json={"ids": ["rol_member"]})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_bulk_update_is_forbidden_for_non_administrators(client: AsyncClient) -> None:
    token = await _member_token(client)

    response = await _bulk_update(
        client, token=token, json={"ids": ["rol_member"], "description": "Nope"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_bulk_update_applies_fields_to_every_id_and_bumps_updated_at(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    first = await _new_role(client, token=token, title="Editor", description="Can edit posts")
    second = await _new_role(client, token=token, title="Reviewer")

    response = await _bulk_update(
        client,
        token=token,
        json={
            "ids": [first["id"], second["id"]],
            "description": "  Shared  ",
            "status": "inactive",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 2, "failed": []}

    for created in (first, second):
        stored = await _get(client, token=token, role_id=created["id"])
        assert stored["description"] == "Shared"
        assert stored["status"] == "inactive"
        assert stored["updatedAt"] != created["updatedAt"]


async def test_bulk_update_deduplicates_ids(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _bulk_update(
        client, token=token, json={"ids": [created["id"], created["id"]], "status": "inactive"}
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 1, "failed": []}
    assert (await _get(client, token=token, role_id=created["id"]))["status"] == "inactive"


async def test_bulk_update_reports_unknown_ids_as_not_found(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _bulk_update(
        client,
        token=token,
        json={"ids": [created["id"], "rol_missing"], "status": "inactive"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "updated": 1,
        "failed": [{"id": "rol_missing", "reason": "not_found"}],
    }


async def test_bulk_update_reports_system_role_when_setting_inactive(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    custom = await _new_role(client, token=token, title="Editor")

    response = await _bulk_update(
        client,
        token=token,
        json={"ids": ["rol_admin", "rol_member", custom["id"]], "status": "inactive"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "updated": 1,
        "failed": [
            {"id": "rol_admin", "reason": "system_role"},
            {"id": "rol_member", "reason": "system_role"},
        ],
    }
    assert (await _get(client, token=token, role_id="rol_admin"))["status"] == "active"
    assert (await _get(client, token=token, role_id=custom["id"]))["status"] == "inactive"


async def test_bulk_update_treats_an_over_length_description_as_per_id_validation(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    first = await _new_role(client, token=token, title="Editor", description="Can edit posts")
    second = await _new_role(client, token=token, title="Reviewer")

    response = await _bulk_update(
        client, token=token, json={"ids": [first["id"], second["id"]], "description": "x" * 501}
    )

    assert response.status_code == 200
    assert response.json() == {
        "updated": 0,
        "failed": [
            {"id": first["id"], "reason": "validation"},
            {"id": second["id"], "reason": "validation"},
        ],
    }
    stored = await _get(client, token=token, role_id=first["id"])
    assert stored["description"] == "Can edit posts"
    assert stored["updatedAt"] == first["updatedAt"]


async def test_bulk_update_trims_and_clears_description(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor", description="Can edit posts")

    cleared = await _bulk_update(
        client, token=token, json={"ids": [created["id"]], "description": None}
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"updated": 1, "failed": []}
    assert (await _get(client, token=token, role_id=created["id"]))["description"] is None

    blank = await _bulk_update(
        client, token=token, json={"ids": [created["id"]], "description": "   "}
    )
    assert blank.status_code == 200
    assert (await _get(client, token=token, role_id=created["id"]))["description"] is None

    a_lim = await _bulk_update(
        client, token=token, json={"ids": [created["id"]], "description": "z" * 500}
    )
    assert a_lim.status_code == 200
    assert (await _get(client, token=token, role_id=created["id"]))["description"] == "z" * 500


async def test_bulk_update_only_status_leaves_description_unchanged(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor", description="Can edit posts")

    response = await _bulk_update(
        client, token=token, json={"ids": [created["id"]], "status": "inactive"}
    )

    assert response.status_code == 200
    stored = await _get(client, token=token, role_id=created["id"])
    assert stored["status"] == "inactive"
    assert stored["description"] == "Can edit posts"


async def test_bulk_update_rejects_title_with_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _bulk_update(
        client, token=token, json={"ids": [created["id"]], "title": "Hacked"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert (await _get(client, token=token, role_id=created["id"]))["title"] == "Editor"


async def test_bulk_update_requires_description_or_status(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _bulk_update(client, token=token, json={"ids": [created["id"]]})

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_bulk_update_rejects_empty_or_malformed_ids(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    no_ids = await _bulk_update(client, token=token, json={"description": "x"})
    empty_ids = await _bulk_update(client, token=token, json={"ids": [], "description": "x"})
    non_array = await _bulk_update(
        client, token=token, json={"ids": "rol_member", "description": "x"}
    )
    non_string = await _bulk_update(client, token=token, json={"ids": [1], "description": "x"})

    for response in (no_ids, empty_ids, non_array, non_string):
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"


async def test_bulk_update_rejects_a_malformed_body_with_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    headers = {**_auth(token), "Content-Type": "application/json"}

    invalid_json = await client.patch("/api/v1/roles/bulk", content=b"{not json", headers=headers)
    not_an_object = await client.patch("/api/v1/roles/bulk", content=b"[]", headers=headers)
    invalid_status = await _bulk_update(
        client, token=token, json={"ids": ["rol_member"], "status": "retired"}
    )
    null_status = await _bulk_update(
        client, token=token, json={"ids": ["rol_member"], "status": None}
    )
    invalid_description = await _bulk_update(
        client, token=token, json={"ids": ["rol_member"], "description": 42}
    )

    for response in (
        invalid_json,
        not_an_object,
        invalid_status,
        null_status,
        invalid_description,
    ):
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"


async def test_bulk_update_duplicate_not_found_id_is_reported_once(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    response = await _bulk_update(
        client,
        token=token,
        json={"ids": ["rol_missing", "rol_missing"], "status": "inactive"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "updated": 0,
        "failed": [{"id": "rol_missing", "reason": "not_found"}],
    }


async def test_bulk_delete_require_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/roles/bulk-delete", json={"ids": ["rol_member"]})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_bulk_delete_is_forbidden_for_non_administrators(client: AsyncClient) -> None:
    token = await _member_token(client)

    response = await _bulk_delete(client, token=token, json={"ids": ["rol_member"]})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_bulk_delete_removes_unused_roles_and_deduplicates_ids(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    first = await _new_role(client, token=token, title="Editor")
    second = await _new_role(client, token=token, title="Reviewer")

    response = await _bulk_delete(
        client,
        token=token,
        json={"ids": [first["id"], second["id"], first["id"]]},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 2, "failed": []}
    for created in (first, second):
        fetched = await client.get(f"/api/v1/roles/{created['id']}", headers=_auth(token))
        assert fetched.status_code == 404


async def test_bulk_delete_reports_not_found_per_id(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _bulk_delete(client, token=token, json={"ids": [created["id"], "rol_missing"]})

    assert response.status_code == 200
    assert response.json() == {
        "deleted": 1,
        "failed": [{"id": "rol_missing", "reason": "not_found"}],
    }


async def test_bulk_delete_reports_system_role_before_referenced(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    # The Administrator holds rol_admin, so checking references first would wrongly
    # report ``referenced``; the System Role guard must win.
    response = await _bulk_delete(client, token=token, json={"ids": ["rol_admin"]})

    assert response.status_code == 200
    assert response.json() == {
        "deleted": 0,
        "failed": [{"id": "rol_admin", "reason": "system_role"}],
    }
    assert (await _get(client, token=token, role_id="rol_admin"))["id"] == "rol_admin"


async def test_bulk_delete_reports_a_role_held_by_a_user_as_referenced(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")
    registered = await client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": "ada@example.com", "password": _PASSWORD},
    )
    user_id = registered.json()["user"]["id"]
    assigned = await client.patch(
        f"/api/v1/users/{user_id}/role",
        json={"roleId": created["id"]},
        headers=_auth(token),
    )
    assert assigned.status_code == 200

    response = await _bulk_delete(client, token=token, json={"ids": [created["id"]]})

    assert response.status_code == 200
    assert response.json() == {
        "deleted": 0,
        "failed": [{"id": created["id"], "reason": "referenced"}],
    }
    assert (await _get(client, token=token, role_id=created["id"]))["id"] == created["id"]


async def test_bulk_delete_mixed_batch_reports_each_id_once_in_order(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    unused = await _new_role(client, token=token, title="Editor")
    held = await _new_role(client, token=token, title="Reviewer")
    registered = await client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": "ada@example.com", "password": _PASSWORD},
    )
    user_id = registered.json()["user"]["id"]
    assigned = await client.patch(
        f"/api/v1/users/{user_id}/role",
        json={"roleId": held["id"]},
        headers=_auth(token),
    )
    assert assigned.status_code == 200

    response = await _bulk_delete(
        client,
        token=token,
        json={
            "ids": ["rol_missing", "rol_admin", held["id"], unused["id"], unused["id"]],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "deleted": 1,
        "failed": [
            {"id": "rol_missing", "reason": "not_found"},
            {"id": "rol_admin", "reason": "system_role"},
            {"id": held["id"], "reason": "referenced"},
        ],
    }


async def test_bulk_delete_rejects_empty_or_malformed_ids_with_400(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    headers = {**_auth(token), "Content-Type": "application/json"}

    no_ids = await _bulk_delete(client, token=token, json={})
    empty_ids = await _bulk_delete(client, token=token, json={"ids": []})
    non_array = await _bulk_delete(client, token=token, json={"ids": "rol_member"})
    non_string = await _bulk_delete(client, token=token, json={"ids": [None]})
    invalid_json = await client.post(
        "/api/v1/roles/bulk-delete", content=b"{not json", headers=headers
    )

    for response in (no_ids, empty_ids, non_array, non_string, invalid_json):
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"


async def test_bulk_update_classifies_each_id_independently(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _bulk_update(
        client,
        token=token,
        json={"ids": ["rol_missing", created["id"]], "description": "x" * 501},
    )

    assert response.status_code == 200
    assert response.json() == {
        "updated": 0,
        "failed": [
            {"id": "rol_missing", "reason": "not_found"},
            {"id": created["id"], "reason": "validation"},
        ],
    }
