"""Role endpoints: reads, single writes, and Administrator bulk operations."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_admin, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.text import escape_like
from app.core.time import to_utc, utcnow
from app.models.role import Role, RoleStatus
from app.models.user import User
from app.schemas.role import Role as RoleOut
from app.schemas.role import (
    RoleBulkDeleteResponse,
    RoleBulkFailure,
    RoleBulkUpdateResponse,
    RoleCreateRequest,
    RoleUpdateRequest,
)

router = APIRouter(prefix="/roles", tags=["roles"])

_ROLE_NOT_FOUND_DETAIL = "No role exists with this id."
_DUPLICATE_TITLE_DETAIL = "A role with this title already exists."
_SYSTEM_ROLE_INACTIVE_DETAIL = "A system role cannot be set inactive."
_SYSTEM_ROLE_DELETE_DETAIL = "A system role cannot be deleted."
_ROLE_IN_USE_DETAIL = "A role held by a user cannot be deleted."
_INVALID_SORT_FIELD_DETAIL = "Unknown sort field."
_INVALID_STATUS_DETAIL = "Unknown role status."
_MALFORMED_BODY_DETAIL = "The request body is malformed."
_INVALID_IDS_DETAIL = "The ids field must be a non-empty array of strings."
_BULK_TITLE_DETAIL = "A title cannot be bulk updated."
_BULK_NO_FIELDS_DETAIL = "At least one of description or status is required."
_INVALID_DESCRIPTION_DETAIL = "The description must be a string or null."
_INVALID_BULK_STATUS_DETAIL = "The status must be active or inactive."

# Sort order is the contract's declared order: active before inactive.
_STATUS_SORT_ORDER = {RoleStatus.ACTIVE.value: 0, RoleStatus.INACTIVE.value: 1}

_SORT_KEYS: dict[str, Any] = {
    # Title sorting is case-insensitive, matching the default order.
    "title": func.lower(Role.title),
    "status": case(_STATUS_SORT_ORDER, value=Role.status, else_=len(_STATUS_SORT_ORDER)),
    "createdAt": Role.created_at,
    "updatedAt": Role.updated_at,
}


def _statuses(raw: list[str] | None) -> list[str]:
    """Map repeated ``status`` values to Role statuses, ignoring empty repeats.

    An unknown value is malformed input (422), so typos never silently widen the result.
    """
    statuses: list[str] = []
    for value in raw or ():
        if not value.strip():
            continue
        try:
            statuses.append(RoleStatus(value).value)
        except ValueError:
            raise ProblemDetailError(
                422, ErrorCode.VALIDATION_ERROR, _INVALID_STATUS_DETAIL
            ) from None
    return statuses


@router.get("", response_model=list[RoleOut], operation_id="listRoles")
async def list_roles(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    title_like: Annotated[str | None, Query()] = None,
    description_like: Annotated[str | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    created_at_gte: Annotated[AwareDatetime | None, Query(alias="createdAt_gte")] = None,
    created_at_lte: Annotated[AwareDatetime | None, Query(alias="createdAt_lte")] = None,
    updated_at_gte: Annotated[AwareDatetime | None, Query(alias="updatedAt_gte")] = None,
    updated_at_lte: Annotated[AwareDatetime | None, Query(alias="updatedAt_lte")] = None,
    _start: Annotated[int, Query(ge=0)] = 0,
    _end: Annotated[int | None, Query(ge=0)] = None,
    _sort: Annotated[str, Query()] = "title",
    _order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> list[Role]:
    """Return roles filtered, sorted, and paginated, with the total in ``x-total-count``."""
    conditions: list[Any] = []
    if title_like is not None:
        conditions.append(Role.title.ilike(f"%{escape_like(title_like)}%", escape="\\"))
    if description_like is not None:
        conditions.append(Role.description.ilike(f"%{escape_like(description_like)}%", escape="\\"))

    statuses = _statuses(status)
    if statuses:
        conditions.append(Role.status.in_(statuses))

    created_gte = to_utc(created_at_gte)
    if created_gte is not None:
        conditions.append(Role.created_at >= created_gte)
    created_lte = to_utc(created_at_lte)
    if created_lte is not None:
        conditions.append(Role.created_at <= created_lte)
    updated_gte = to_utc(updated_at_gte)
    if updated_gte is not None:
        conditions.append(Role.updated_at >= updated_gte)
    updated_lte = to_utc(updated_at_lte)
    if updated_lte is not None:
        conditions.append(Role.updated_at <= updated_lte)

    total = await db.scalar(select(func.count()).select_from(Role).where(*conditions))

    sort_key = _SORT_KEYS.get(_sort)
    if sort_key is None:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_SORT_FIELD_DETAIL)
    order = sort_key.asc() if _order == "asc" else sort_key.desc()

    statement = select(Role).where(*conditions).order_by(order, Role.id).offset(_start)
    if _end is not None:
        statement = statement.limit(max(0, _end - _start))

    roles = list((await db.scalars(statement)).all())
    response.headers["x-total-count"] = str(total or 0)
    return roles


_MAX_DESCRIPTION_LENGTH = 500


async def _json_object(request: Request) -> dict[str, Any]:
    """Parse the JSON body as an object; anything else is a malformed 400."""
    try:
        body = await request.json()
    except ValueError:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _MALFORMED_BODY_DETAIL) from None
    if not isinstance(body, dict):
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _MALFORMED_BODY_DETAIL)
    return body


def _bulk_ids(body: dict[str, Any]) -> list[str]:
    """Return the deduplicated ``ids`` in first-seen order, or reject a malformed list."""
    raw = body.get("ids")
    if not isinstance(raw, list) or not raw:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_IDS_DETAIL)

    ids: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_IDS_DETAIL)
        # A repeated id is applied and reported once.
        if value not in seen:
            seen.add(value)
            ids.append(value)
    return ids


def _bulk_description(body: dict[str, Any]) -> tuple[bool, str | None, bool]:
    """Return (present, trimmed description, over-length).

    A blank description is normalised to null. An over-length description is not a
    malformed request: it becomes a per-id ``validation`` failure.
    """
    if "description" not in body:
        return False, None, False
    value = body["description"]
    if value is None:
        return True, None, False
    if not isinstance(value, str):
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_DESCRIPTION_DETAIL)
    trimmed = value.strip()
    if len(trimmed) > _MAX_DESCRIPTION_LENGTH:
        return True, None, True
    return True, trimmed or None, False


def _bulk_status(body: dict[str, Any]) -> tuple[bool, RoleStatus | None]:
    """Return (present, Role status); a null or unknown status is malformed."""
    if "status" not in body:
        return False, None
    value = body["status"]
    if not isinstance(value, str):
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_BULK_STATUS_DETAIL)
    try:
        return True, RoleStatus(value)
    except ValueError:
        raise ProblemDetailError(
            400, ErrorCode.VALIDATION_ERROR, _INVALID_BULK_STATUS_DETAIL
        ) from None


async def _title_is_taken(db: AsyncSession, title: str, *, exclude_id: str | None = None) -> bool:
    """Return True if another Role already uses ``title``, ignoring case."""
    statement = select(Role.id).where(func.lower(Role.title) == title.lower())
    if exclude_id is not None:
        statement = statement.where(Role.id != exclude_id)
    return await db.scalar(statement) is not None


@router.post("", status_code=201, response_model=RoleOut, operation_id="createRole")
async def create_role(
    payload: RoleCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin)],
) -> Role:
    """Create a Role (Administrator only); a duplicate title is 409."""
    if await _title_is_taken(db, payload.title):
        raise ProblemDetailError(409, ErrorCode.CONFLICT, _DUPLICATE_TITLE_DETAIL)

    now = utcnow()
    role = Role(
        title=payload.title,
        description=payload.description,
        status=payload.status.value,
        created_at=now,
        updated_at=now,
    )
    db.add(role)
    try:
        await db.flush()
    except IntegrityError:
        # The lower(title) unique index is the last line of defence for a race.
        raise ProblemDetailError(409, ErrorCode.CONFLICT, _DUPLICATE_TITLE_DETAIL) from None
    return role


@router.patch("/bulk", response_model=RoleBulkUpdateResponse, operation_id="bulkUpdateRoles")
async def bulk_update_roles(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin)],
) -> RoleBulkUpdateResponse:
    """Bulk-update Role descriptions/statuses (Administrator only); per-id failures reported.

    The body is parsed by hand so every malformed payload is a 400 (the contract's
    BadRequest), while an over-length description becomes a per-id ``validation``
    failure instead of sinking the whole batch.
    """
    body = await _json_object(request)
    ids = _bulk_ids(body)

    if "title" in body:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _BULK_TITLE_DETAIL)

    has_description, description, description_too_long = _bulk_description(body)
    has_status, status = _bulk_status(body)
    if not has_description and not has_status:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _BULK_NO_FIELDS_DETAIL)

    roles = (await db.scalars(select(Role).where(Role.id.in_(ids)))).all()
    roles_by_id = {role.id: role for role in roles}

    updated = 0
    failed: list[RoleBulkFailure] = []
    now = utcnow()
    for role_id in ids:
        role = roles_by_id.get(role_id)
        if role is None:
            failed.append(RoleBulkFailure(id=role_id, reason="not_found"))
            continue

        if has_status and status is RoleStatus.INACTIVE and role.is_system:
            failed.append(RoleBulkFailure(id=role_id, reason="system_role"))
            continue
        if description_too_long:
            failed.append(RoleBulkFailure(id=role_id, reason="validation"))
            continue

        if has_status and status is not None:
            role.status = status.value
        if has_description:
            role.description = description

        role.updated_at = now
        updated += 1

    await db.flush()
    return RoleBulkUpdateResponse(updated=updated, failed=failed)


@router.post("/bulk-delete", response_model=RoleBulkDeleteResponse, operation_id="bulkDeleteRoles")
async def bulk_delete_roles(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin)],
) -> RoleBulkDeleteResponse:
    """Bulk-delete Roles (Administrator only); per-id failures reported.

    System Roles are rejected before the held-by-a-User check, so a System Role that
    is also held is unambiguously reported as ``system_role``.
    """
    body = await _json_object(request)
    ids = _bulk_ids(body)

    roles = (await db.scalars(select(Role).where(Role.id.in_(ids)))).all()
    roles_by_id = {role.id: role for role in roles}

    held_ids = set((await db.scalars(select(User.role_id).where(User.role_id.in_(ids)))).all())

    deleted = 0
    failed: list[RoleBulkFailure] = []
    for role_id in ids:
        role = roles_by_id.get(role_id)
        if role is None:
            failed.append(RoleBulkFailure(id=role_id, reason="not_found"))
        elif role.is_system:
            failed.append(RoleBulkFailure(id=role_id, reason="system_role"))
        elif role.id in held_ids:
            failed.append(RoleBulkFailure(id=role_id, reason="referenced"))
        else:
            await db.delete(role)
            deleted += 1

    await db.flush()
    return RoleBulkDeleteResponse(deleted=deleted, failed=failed)


@router.patch("/{id}", response_model=RoleOut, operation_id="updateRole")
async def update_role(
    id: str,
    payload: RoleUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin)],
) -> Role:
    """Partially update a Role (Administrator only); server-managed fields are ignored."""
    role = await db.get(Role, id)
    if role is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _ROLE_NOT_FOUND_DETAIL)

    fields = payload.model_fields_set

    if "title" in fields and payload.title is not None:
        if await _title_is_taken(db, payload.title, exclude_id=id):
            raise ProblemDetailError(409, ErrorCode.CONFLICT, _DUPLICATE_TITLE_DETAIL)
        role.title = payload.title
    if "description" in fields:
        role.description = payload.description
    if "status" in fields and payload.status is not None:
        if role.is_system and payload.status is RoleStatus.INACTIVE:
            raise ProblemDetailError(409, ErrorCode.CONFLICT, _SYSTEM_ROLE_INACTIVE_DETAIL)
        role.status = payload.status.value

    # An empty body (or only ignored fields) is a 200 no-op that must not bump the instant.
    if fields:
        role.updated_at = utcnow()

    try:
        await db.flush()
    except IntegrityError:
        raise ProblemDetailError(409, ErrorCode.CONFLICT, _DUPLICATE_TITLE_DETAIL) from None
    return role


@router.delete("/{id}", status_code=204, operation_id="deleteRole")
async def delete_role(
    id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin)],
) -> Response:
    """Delete a Role (Administrator only); System Roles and held Roles are 409."""
    role = await db.get(Role, id)
    if role is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _ROLE_NOT_FOUND_DETAIL)

    if role.is_system:
        raise ProblemDetailError(409, ErrorCode.CONFLICT, _SYSTEM_ROLE_DELETE_DETAIL)

    holder = await db.scalar(select(User.id).where(User.role_id == id).limit(1))
    if holder is not None:
        raise ProblemDetailError(409, ErrorCode.CONFLICT, _ROLE_IN_USE_DETAIL)

    await db.delete(role)
    return Response(status_code=204)


@router.get("/{id}", response_model=RoleOut, operation_id="getRole")
async def get_role(
    id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Role:
    """Return the Role with ``id``, or 404."""
    role = await db.get(Role, id)
    if role is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _ROLE_NOT_FOUND_DETAIL)
    return role
