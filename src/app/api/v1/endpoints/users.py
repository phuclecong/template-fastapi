"""User endpoints: list, current profile, role change, and delete (GET/PATCH/DELETE /users)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_admin, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.models.task import Task
from app.models.user import Role, User
from app.schemas.user import UpdateRoleRequest
from app.schemas.user import User as UserOut

router = APIRouter(prefix="/users", tags=["users"])

_USER_NOT_FOUND_DETAIL = "No user exists with this id."
_LAST_ADMIN_DETAIL = "Cannot demote the last admin."
_SELF_DELETE_DETAIL = "An admin cannot delete their own account."
_LAST_ADMIN_DELETE_DETAIL = "Cannot delete the last admin."


async def _admin_count(db: AsyncSession) -> int:
    """Return the number of users with the ``admin`` role."""
    return (
        await db.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN.value))
    ) or 0


@router.get("/me", response_model=UserOut)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the authenticated user's own profile."""
    return current_user


@router.get("", response_model=list[UserOut])
async def list_users(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    _start: Annotated[int, Query(ge=0)] = 0,
    _end: Annotated[int | None, Query(ge=0)] = None,
) -> list[User]:
    """Return a paginated slice of users, with the total in ``x-total-count``."""
    total = await db.scalar(select(func.count()).select_from(User))
    statement = select(User).order_by(User.created_at, User.id).offset(_start)
    if _end is not None:
        statement = statement.limit(max(0, _end - _start))
    users = list((await db.scalars(statement)).all())
    response.headers["x-total-count"] = str(total or 0)
    return users


@router.patch("/{id}/role", response_model=UserOut)
async def update_user_role(
    id: str,
    payload: UpdateRoleRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin)],
) -> User:
    """Change a user's role (admin only); demoting the last admin is blocked."""
    target = await db.get(User, id)
    if target is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _USER_NOT_FOUND_DETAIL)

    if (
        target.role == Role.ADMIN.value
        and payload.role == Role.MEMBER
        and await _admin_count(db) <= 1
    ):
        raise ProblemDetailError(403, ErrorCode.FORBIDDEN, _LAST_ADMIN_DETAIL)

    target.role = payload.role.value
    return target


@router.delete("/{id}", status_code=204)
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

    if target.role == Role.ADMIN.value and await _admin_count(db) <= 1:
        raise ProblemDetailError(403, ErrorCode.FORBIDDEN, _LAST_ADMIN_DELETE_DETAIL)

    if target.id == admin.id:
        raise ProblemDetailError(403, ErrorCode.FORBIDDEN, _SELF_DELETE_DETAIL)

    # Unassign the user's tasks before deleting so the FK (ondelete="SET NULL") is
    # honored regardless of backend FK enforcement (SQLite in tests does not enforce).
    await db.execute(update(Task).where(Task.assignee_id == id).values(assignee_id=None))
    await db.delete(target)
    return Response(status_code=204)
