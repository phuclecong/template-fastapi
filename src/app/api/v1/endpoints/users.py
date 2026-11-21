"""User endpoints: list, current profile, role change, and delete (GET/PATCH/DELETE /users)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_admin, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.text import escape_like
from app.models.role import ADMIN_ROLE_ID, Role, RoleStatus
from app.models.task import Task
from app.models.user import User
from app.schemas.user import UpdateRoleRequest
from app.schemas.user import User as UserOut

router = APIRouter(prefix="/users", tags=["users"])

_USER_NOT_FOUND_DETAIL = "No user exists with this id."
_LAST_ADMIN_DETAIL = "Cannot demote the last admin."
_SELF_DELETE_DETAIL = "An admin cannot delete their own account."
_LAST_ADMIN_DELETE_DETAIL = "Cannot delete the last admin."
_INVALID_SORT_FIELD_DETAIL = "Unknown sort field."
_INVALID_ROLE_DETAIL = "No active role exists with the given roleId."

_SORT_KEYS: dict[str, Any] = {
    "name": User.name,
    "email": User.email,
    "roleId": User.role_id,
    "createdAt": User.created_at,
}


async def _admin_count(db: AsyncSession) -> int:
    """Return the number of users holding the Administrator System Role."""
    return (
        await db.scalar(select(func.count()).select_from(User).where(User.is_administrator))
    ) or 0


@router.get("/me", response_model=UserOut, operation_id="getCurrentUser")
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the authenticated user's own profile."""
    return current_user


@router.get("", response_model=list[UserOut], operation_id="listUsers")
async def list_users(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str | None, Query()] = None,
    role_id: Annotated[str | None, Query(alias="roleId")] = None,
    _start: Annotated[int, Query(ge=0)] = 0,
    _end: Annotated[int | None, Query(ge=0)] = None,
    _sort: Annotated[str, Query()] = "name",
    _order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> list[User]:
    """Return users filtered, sorted, and paginated, with the total in ``x-total-count``."""
    conditions: list[Any] = []
    if q is not None:
        pattern = f"%{escape_like(q)}%"
        conditions.append(
            or_(
                User.name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    if role_id is not None:
        conditions.append(User.role_id == role_id)

    total = await db.scalar(select(func.count()).select_from(User).where(*conditions))

    sort_key = _SORT_KEYS.get(_sort)
    if sort_key is None:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_SORT_FIELD_DETAIL)
    order = sort_key.asc() if _order == "asc" else sort_key.desc()

    statement = select(User).where(*conditions).order_by(order, User.id).offset(_start)
    if _end is not None:
        statement = statement.limit(max(0, _end - _start))

    users = list((await db.scalars(statement)).all())
    response.headers["x-total-count"] = str(total or 0)
    return users


@router.patch("/{id}/role", response_model=UserOut, operation_id="updateUserRole")
async def update_user_role(
    id: str,
    payload: UpdateRoleRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin)],
) -> User:
    """Change a user's Role (admin only); demoting the last admin is blocked."""
    target = await db.get(User, id)
    if target is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _USER_NOT_FOUND_DETAIL)

    new_role = await db.get(Role, payload.role_id)
    if new_role is None or new_role.status != RoleStatus.ACTIVE.value:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_ROLE_DETAIL)

    if target.is_administrator and new_role.id != ADMIN_ROLE_ID and await _admin_count(db) <= 1:
        raise ProblemDetailError(403, ErrorCode.FORBIDDEN, _LAST_ADMIN_DETAIL)

    # Assign the relationship only; flushing synchronizes ``role_id`` so the response
    # reflects both the new identity and the embedded Role summary.
    target.role = new_role
    await db.flush()
    return target


@router.delete("/{id}", status_code=204, operation_id="deleteUser")
async def delete_user(
    id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> Response:
    """Delete a user (admin only); their tasks are unassigned, not deleted.

    An admin cannot delete their own account, nor the last remaining admin.
    """
    target = await db.get(User, id)
    if target is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _USER_NOT_FOUND_DETAIL)

    if target.is_administrator and await _admin_count(db) <= 1:
        raise ProblemDetailError(403, ErrorCode.FORBIDDEN, _LAST_ADMIN_DELETE_DETAIL)

    if target.id == admin.id:
        raise ProblemDetailError(403, ErrorCode.FORBIDDEN, _SELF_DELETE_DETAIL)

    # Unassign the user's tasks before deleting so the FK (ondelete="SET NULL") is
    # honored regardless of backend FK enforcement (SQLite in tests does not enforce).
    await db.execute(update(Task).where(Task.assignee_id == id).values(assignee_id=None))
    await db.delete(target)
    return Response(status_code=204)
