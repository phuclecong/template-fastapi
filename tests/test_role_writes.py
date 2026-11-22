"""Role catalogue writes: POST /roles, PATCH /roles/{id}, DELETE /roles/{id}."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.role import Role
from app.models.user import User
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


def _create(client: AsyncClient, *, token: str, json: dict[str, Any]) -> Any:
    return client.post("/api/v1/roles", json=json, headers=_auth(token))


def _patch(client: AsyncClient, *, token: str, role_id: str, json: dict[str, Any]) -> Any:
    return client.patch(f"/api/v1/roles/{role_id}", json=json, headers=_auth(token))


def _delete(client: AsyncClient, *, token: str, role_id: str) -> Any:
    return client.delete(f"/api/v1/roles/{role_id}", headers=_auth(token))


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
    response = await _create(client, token=token, json=payload)
    assert response.status_code == 201
    return response.json()


async def test_create_returns_full_role_with_trimmed_input_and_active_default(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    response = await _create(
        client,
        token=token,
        json={"title": "  Editor  ", "description": "  Can edit posts  "},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("rol_")
    assert body["title"] == "Editor"
    assert body["description"] == "Can edit posts"
    assert body["status"] == "active"
    assert body["createdAt"] == body["updatedAt"]

    fetched = await client.get(f"/api/v1/roles/{body['id']}", headers=_auth(token))
    assert fetched.status_code == 200
    assert fetched.json() == body


async def test_created_role_id_fits_stored_columns(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Regression: ``rol_`` + UUID is 40 chars, so both columns must hold 40."""
    token = await _admin_token(client, session_factory)

    response = await _create(client, token=token, json={"title": "Editor"})

    assert response.status_code == 201
    role_id = response.json()["id"]
    role_column = Role.__table__.c.id.type
    user_role_column = User.__table__.c.role_id.type
    assert isinstance(role_column, String)
    assert isinstance(user_role_column, String)
    assert role_column.length == 40
    assert user_role_column.length == 40
    assert len(role_id) <= (role_column.length or 0)
    assert len(role_id) <= (user_role_column.length or 0)


async def test_create_stores_blank_description_as_null(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    response = await _create(client, token=token, json={"title": "Editor", "description": "   "})

    assert response.status_code == 201
    assert response.json()["description"] is None


async def test_create_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/roles", json={"title": "Editor"})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_create_forbidden_for_non_administrator(client: AsyncClient) -> None:
    token = await _member_token(client)

    response = await _create(client, token=token, json={"title": "Editor"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_create_rejects_duplicate_title_case_insensitively(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    assert (await _create(client, token=token, json={"title": "Editor"})).status_code == 201

    same_case = await _create(client, token=token, json={"title": "Editor"})
    different_case = await _create(client, token=token, json={"title": "  eDiToR  "})

    assert same_case.status_code == 409
    assert same_case.json()["code"] == "conflict"
    assert different_case.status_code == 409
    assert different_case.json()["code"] == "conflict"


async def test_create_validates_trimmed_title_and_description_lengths(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    blank_title = await _create(client, token=token, json={"title": "   "})
    long_title = await _create(client, token=token, json={"title": "x" * 101})
    long_description = await _create(
        client, token=token, json={"title": "Editor", "description": "x" * 501}
    )
    at_limit = await _create(
        client, token=token, json={"title": "y" * 100, "description": "z" * 500}
    )

    assert blank_title.status_code == 422
    assert long_title.status_code == 422
    assert long_description.status_code == 422
    assert at_limit.status_code == 201
    assert at_limit.json()["title"] == "y" * 100
    assert at_limit.json()["description"] == "z" * 500


async def test_create_accepts_explicit_inactive_status(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    response = await _create(client, token=token, json={"title": "Retired", "status": "inactive"})

    assert response.status_code == 201
    assert response.json()["status"] == "inactive"


async def test_patch_changes_only_supplied_fields(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor", description="Can edit posts")

    response = await _patch(
        client, token=token, role_id=created["id"], json={"title": "  Senior Editor  "}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["title"] == "Senior Editor"
    assert body["description"] == "Can edit posts"
    assert body["status"] == "active"
    assert body["createdAt"] == created["createdAt"]


async def test_patch_ignores_server_managed_fields(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _patch(
        client,
        token=token,
        role_id=created["id"],
        json={
            "id": "rol_hacked",
            "createdAt": "2000-01-01T00:00:00Z",
            "updatedAt": "2000-01-01T00:00:00Z",
            "title": "Editor",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["createdAt"] == created["createdAt"]
    assert body["updatedAt"] != "2000-01-01T00:00:00Z"


async def test_patch_empty_is_a_noop_and_does_not_bump_updated_at(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor", description="Can edit posts")

    response = await _patch(client, token=token, role_id=created["id"], json={})

    assert response.status_code == 200
    assert response.json() == created


async def test_patch_unknown_role_returns_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    response = await _patch(client, token=token, role_id="rol_missing", json={"title": "Nope"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_patch_rejects_duplicate_title_but_excludes_itself(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    editor = await _new_role(client, token=token, title="Editor")
    await _new_role(client, token=token, title="Reviewer")

    conflict = await _patch(client, token=token, role_id=editor["id"], json={"title": "reviewer"})
    same_role = await _patch(client, token=token, role_id=editor["id"], json={"title": "EDITOR"})

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "conflict"
    assert same_role.status_code == 200
    assert same_role.json()["title"] == "EDITOR"


async def test_patch_explicit_or_blank_null_description_clears_it(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor", description="Can edit posts")

    explicit_null = await _patch(
        client, token=token, role_id=created["id"], json={"description": None}
    )
    assert explicit_null.status_code == 200
    assert explicit_null.json()["description"] is None

    restored = await _patch(
        client, token=token, role_id=created["id"], json={"description": "Can edit posts"}
    )
    assert restored.json()["description"] == "Can edit posts"

    blank = await _patch(client, token=token, role_id=created["id"], json={"description": "   "})
    assert blank.status_code == 200
    assert blank.json()["description"] is None


async def test_patch_rejects_null_title_or_status(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    null_title = await _patch(client, token=token, role_id=created["id"], json={"title": None})
    null_status = await _patch(client, token=token, role_id=created["id"], json={"status": None})

    assert null_title.status_code == 422
    assert null_status.status_code == 422


async def test_patch_bumps_updated_at_on_a_successful_write(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _patch(client, token=token, role_id=created["id"], json={"status": "inactive"})

    assert response.status_code == 200
    assert response.json()["updatedAt"] != created["updatedAt"]
    assert response.json()["status"] == "inactive"


async def test_patch_cannot_set_a_system_role_inactive(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    for role_id in ("rol_admin", "rol_member"):
        response = await _patch(client, token=token, role_id=role_id, json={"status": "inactive"})
        assert response.status_code == 409
        assert response.json()["code"] == "conflict"

    unchanged = await client.get("/api/v1/roles/rol_admin", headers=_auth(token))
    assert unchanged.json()["status"] == "active"


async def test_patch_renames_a_system_role_without_changing_identity(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    response = await _patch(
        client, token=token, role_id="rol_admin", json={"title": "Workspace Owner"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "rol_admin"
    assert body["title"] == "Workspace Owner"

    # Authorization is by identity, so the renamed System Role still gates writes.
    created = await _create(client, token=token, json={"title": "Editor"})
    assert created.status_code == 201


async def test_delete_removes_an_unused_custom_role(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)
    created = await _new_role(client, token=token, title="Editor")

    response = await _delete(client, token=token, role_id=created["id"])

    assert response.status_code == 204
    assert response.content == b""
    fetched = await client.get(f"/api/v1/roles/{created['id']}", headers=_auth(token))
    assert fetched.status_code == 404


async def test_delete_system_role_returns_409(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    for role_id in ("rol_admin", "rol_member"):
        response = await _delete(client, token=token, role_id=role_id)
        assert response.status_code == 409
        assert response.json()["code"] == "conflict"

    still_there = await client.get("/api/v1/roles/rol_admin", headers=_auth(token))
    assert still_there.status_code == 200


async def test_delete_role_held_by_a_user_returns_409(
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

    response = await _delete(client, token=token, role_id=created["id"])

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_delete_unknown_role_returns_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _admin_token(client, session_factory)

    response = await _delete(client, token=token, role_id="rol_missing")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_patch_and_delete_require_authentication(client: AsyncClient) -> None:
    patched = await client.patch("/api/v1/roles/rol_member", json={"title": "Nope"})
    deleted = await client.delete("/api/v1/roles/rol_member")

    assert patched.status_code == 401
    assert patched.json()["code"] == "unauthorized"
    assert deleted.status_code == 401
    assert deleted.json()["code"] == "unauthorized"


async def test_patch_and_delete_are_forbidden_for_non_administrators(
    client: AsyncClient,
) -> None:
    token = await _member_token(client)

    patched = await _patch(client, token=token, role_id="rol_member", json={"title": "Nope"})
    deleted = await _delete(client, token=token, role_id="rol_member")

    assert patched.status_code == 403
    assert patched.json()["code"] == "forbidden"
    assert deleted.status_code == 403
    assert deleted.json()["code"] == "forbidden"
