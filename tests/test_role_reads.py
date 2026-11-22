"""Role catalogue reads: GET /roles with filtering/sorting/pagination, and GET /roles/{id}."""

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.role import Role, RoleStatus, new_role_id
from tests.helpers import PASSWORD as _PASSWORD
from tests.helpers import auth as _auth


def _instant(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 5, day, hour, tzinfo=UTC)


async def _token(client: AsyncClient, *, email: str = "ada@example.com") -> str:
    """Register a user (a Member) and return an access token."""
    registered = await client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": _PASSWORD},
    )
    assert registered.status_code == 201
    return registered.json()["accessToken"]


async def _clear_roles(factory: async_sessionmaker[AsyncSession]) -> None:
    """Remove the seeded System Roles so each test controls the catalogue exactly."""
    async with factory() as db:
        await db.execute(delete(Role))
        await db.commit()


async def _seed_role(
    factory: async_sessionmaker[AsyncSession],
    *,
    title: str,
    description: str | None = None,
    status: str = RoleStatus.ACTIVE.value,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    id: str | None = None,
) -> str:
    """Insert a Role directly; Role writes have no HTTP birth path yet."""
    role = Role(
        id=id or new_role_id(),
        title=title,
        description=description,
        status=status,
        created_at=created_at or _instant(1),
        updated_at=updated_at or created_at or _instant(1),
    )
    async with factory() as db:
        db.add(role)
        await db.commit()
    return role.id


async def test_list_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/roles")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_get_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/roles/rol_member")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_list_returns_all_roles_with_total_count(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title in ("Editor", "Reviewer", "Auditor"):
        await _seed_role(session_factory, title=title)

    response = await client.get("/api/v1/roles", headers=_auth(token))

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    assert {role["title"] for role in response.json()} == {"Editor", "Reviewer", "Auditor"}


async def test_list_returns_contract_role_shape(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    role_id = await _seed_role(
        session_factory,
        title="Editor",
        description="Can edit posts",
        status=RoleStatus.INACTIVE.value,
        created_at=_instant(2, 3),
        updated_at=_instant(3, 4),
    )

    response = await client.get("/api/v1/roles", headers=_auth(token))

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": role_id,
            "title": "Editor",
            "description": "Can edit posts",
            "status": "inactive",
            "createdAt": "2024-05-02T03:00:00Z",
            "updatedAt": "2024-05-03T04:00:00Z",
        }
    ]


async def test_get_returns_role(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    role_id = await _seed_role(session_factory, title="Editor", description="Can edit posts")

    response = await client.get(f"/api/v1/roles/{role_id}", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == role_id
    assert body["title"] == "Editor"
    assert body["description"] == "Can edit posts"
    assert body["status"] == "active"
    assert body["createdAt"] == "2024-05-01T00:00:00Z"
    assert body["updatedAt"] == "2024-05-01T00:00:00Z"


async def test_get_unknown_role_returns_404(client: AsyncClient) -> None:
    token = await _token(client)

    response = await client.get("/api/v1/roles/rol_missing", headers=_auth(token))

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_list_filters_title_like_case_insensitively(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title in ("Alpha team", "alpha squad", "Beta team"):
        await _seed_role(session_factory, title=title)

    response = await client.get(
        "/api/v1/roles", params={"title_like": "ALPHA"}, headers=_auth(token)
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    assert {role["title"] for role in response.json()} == {"Alpha team", "alpha squad"}


async def test_list_filters_title_like_escaping_wildcards(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title in ("50% off", "50 back", "under_score", "underXscore"):
        await _seed_role(session_factory, title=title)

    percent = await client.get("/api/v1/roles", params={"title_like": "50%"}, headers=_auth(token))
    underscore = await client.get(
        "/api/v1/roles", params={"title_like": "under_"}, headers=_auth(token)
    )

    assert percent.status_code == 200
    assert [role["title"] for role in percent.json()] == ["50% off"]
    assert underscore.status_code == 200
    assert [role["title"] for role in underscore.json()] == ["under_score"]


async def test_list_filters_description_like_case_insensitively_and_escapes_wildcards(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    await _seed_role(session_factory, title="Billing", description="Handles BILLING")
    await _seed_role(session_factory, title="Support", description="handles support")
    await _seed_role(session_factory, title="Remote", description="100% remote")
    await _seed_role(session_factory, title="Hybrid", description="100x remote")
    await _seed_role(session_factory, title="Untitled")

    billing = await client.get(
        "/api/v1/roles", params={"description_like": "billing"}, headers=_auth(token)
    )
    percent = await client.get(
        "/api/v1/roles", params={"description_like": "100%"}, headers=_auth(token)
    )

    assert billing.status_code == 200
    assert [role["title"] for role in billing.json()] == ["Billing"]
    assert percent.status_code == 200
    assert [role["title"] for role in percent.json()] == ["Remote"]


async def test_list_filters_by_repeated_status_with_or_semantics(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title, status in (
        ("Active A", RoleStatus.ACTIVE.value),
        ("Active B", RoleStatus.ACTIVE.value),
        ("Inactive A", RoleStatus.INACTIVE.value),
        ("Inactive B", RoleStatus.INACTIVE.value),
    ):
        await _seed_role(session_factory, title=title, status=status)

    both = await client.get(
        "/api/v1/roles",
        params=[("status", "active"), ("status", "inactive")],
        headers=_auth(token),
    )
    inactive = await client.get(
        "/api/v1/roles", params={"status": "inactive"}, headers=_auth(token)
    )

    assert both.status_code == 200
    assert both.headers["x-total-count"] == "4"
    assert inactive.status_code == 200
    assert inactive.headers["x-total-count"] == "2"
    assert {role["title"] for role in inactive.json()} == {"Inactive A", "Inactive B"}


async def test_list_ignores_empty_status_repeats(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    await _seed_role(session_factory, title="Active A")
    await _seed_role(session_factory, title="Inactive A", status=RoleStatus.INACTIVE.value)

    response = await client.get(
        "/api/v1/roles",
        params=[("status", ""), ("status", "active")],
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert [role["title"] for role in response.json()] == ["Active A"]


async def test_list_rejects_invalid_status(client: AsyncClient) -> None:
    token = await _token(client)

    response = await client.get("/api/v1/roles", params={"status": "bogus"}, headers=_auth(token))

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_list_filters_created_at_range_inclusively_with_explicit_offsets(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    await _seed_role(session_factory, title="Early", created_at=_instant(1))
    await _seed_role(session_factory, title="Boundary", created_at=_instant(2))
    await _seed_role(session_factory, title="Late", created_at=_instant(3))

    response = await client.get(
        "/api/v1/roles",
        params={
            "createdAt_gte": "2024-05-02T07:00:00+07:00",
            "createdAt_lte": "2024-05-02T07:00:00+07:00",
        },
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert [role["title"] for role in response.json()] == ["Boundary"]


async def test_list_filters_updated_at_range_inclusively(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    await _seed_role(session_factory, title="Old", updated_at=_instant(1))
    await _seed_role(session_factory, title="Mid", updated_at=_instant(2))
    await _seed_role(session_factory, title="New", updated_at=_instant(3))

    response = await client.get(
        "/api/v1/roles",
        params={"updatedAt_gte": "2024-05-02T00:00:00Z", "updatedAt_lte": "2024-05-03T00:00:00Z"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert {role["title"] for role in response.json()} == {"Mid", "New"}


async def test_list_rejects_date_only_and_offsetless_instants(client: AsyncClient) -> None:
    token = await _token(client)

    date_only = await client.get(
        "/api/v1/roles", params={"createdAt_gte": "2024-05-02"}, headers=_auth(token)
    )
    offsetless = await client.get(
        "/api/v1/roles", params={"updatedAt_lte": "2024-05-02T00:00:00"}, headers=_auth(token)
    )

    assert date_only.status_code == 422
    assert date_only.json()["code"] == "validation_error"
    assert offsetless.status_code == 422
    assert offsetless.json()["code"] == "validation_error"


async def test_list_paginates_with_start_and_end_and_counts_before_pagination(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title in ("Alpha", "Bravo", "Charlie", "Delta"):
        await _seed_role(session_factory, title=title)

    response = await client.get(
        "/api/v1/roles", params={"_start": 1, "_end": 3}, headers=_auth(token)
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "4"
    assert [role["title"] for role in response.json()] == ["Bravo", "Charlie"]


async def test_list_default_sort_is_case_insensitive_title_ascending(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title in ("banana", "Apple", "Cherry"):
        await _seed_role(session_factory, title=title)

    response = await client.get("/api/v1/roles", headers=_auth(token))

    assert response.status_code == 200
    assert [role["title"] for role in response.json()] == ["Apple", "banana", "Cherry"]


async def test_list_sorts_by_title_desc(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title in ("banana", "Apple", "Cherry"):
        await _seed_role(session_factory, title=title)

    response = await client.get(
        "/api/v1/roles", params={"_sort": "title", "_order": "desc"}, headers=_auth(token)
    )

    assert response.status_code == 200
    assert [role["title"] for role in response.json()] == ["Cherry", "banana", "Apple"]


async def test_list_sorts_active_before_inactive(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title, status in (
        ("Retired A", RoleStatus.INACTIVE.value),
        ("Current A", RoleStatus.ACTIVE.value),
        ("Retired B", RoleStatus.INACTIVE.value),
        ("Current B", RoleStatus.ACTIVE.value),
    ):
        await _seed_role(session_factory, title=title, status=status)

    response = await client.get("/api/v1/roles", params={"_sort": "status"}, headers=_auth(token))

    assert response.status_code == 200
    assert [role["status"] for role in response.json()] == [
        "active",
        "active",
        "inactive",
        "inactive",
    ]


async def test_list_sorts_by_created_at_desc_and_updated_at_asc(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    await _seed_role(
        session_factory, title="Middle", created_at=_instant(2), updated_at=_instant(3)
    )
    await _seed_role(
        session_factory, title="Newest", created_at=_instant(3), updated_at=_instant(1)
    )
    await _seed_role(
        session_factory, title="Oldest", created_at=_instant(1), updated_at=_instant(2)
    )

    by_created = await client.get(
        "/api/v1/roles", params={"_sort": "createdAt", "_order": "desc"}, headers=_auth(token)
    )
    by_updated = await client.get(
        "/api/v1/roles", params={"_sort": "updatedAt", "_order": "asc"}, headers=_auth(token)
    )

    assert [role["title"] for role in by_created.json()] == ["Newest", "Middle", "Oldest"]
    assert [role["title"] for role in by_updated.json()] == ["Newest", "Oldest", "Middle"]


async def test_list_sort_ties_break_by_id(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    shared = _instant(2)
    await _seed_role(session_factory, id="rol_zulu", title="Zulu", created_at=shared)
    await _seed_role(session_factory, id="rol_alpha", title="Alpha", created_at=shared)

    response = await client.get(
        "/api/v1/roles", params={"_sort": "createdAt"}, headers=_auth(token)
    )

    assert response.status_code == 200
    assert [role["id"] for role in response.json()] == ["rol_alpha", "rol_zulu"]


async def test_list_rejects_unknown_sort_field(client: AsyncClient) -> None:
    token = await _token(client)

    response = await client.get("/api/v1/roles", params={"_sort": "bogus"}, headers=_auth(token))

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


async def test_list_rejects_invalid_order(client: AsyncClient) -> None:
    token = await _token(client)

    response = await client.get(
        "/api/v1/roles", params={"_order": "sideways"}, headers=_auth(token)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_list_combines_filters_with_pagination(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    token = await _token(client)
    await _clear_roles(session_factory)
    for title, status in (
        ("Ship A", RoleStatus.ACTIVE.value),
        ("Ship B", RoleStatus.ACTIVE.value),
        ("Ship C", RoleStatus.ACTIVE.value),
        ("Write tests", RoleStatus.ACTIVE.value),
        ("Ship retired", RoleStatus.INACTIVE.value),
    ):
        await _seed_role(session_factory, title=title, status=status)

    response = await client.get(
        "/api/v1/roles",
        params={"title_like": "ship", "status": "active", "_start": 0, "_end": 2},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    assert [role["title"] for role in response.json()] == ["Ship A", "Ship B"]
