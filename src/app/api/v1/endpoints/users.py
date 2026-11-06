"""User endpoints: list, current profile, and role change (GET /users, PATCH /users/{id}/role)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_admin, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.models.user import Role, User
from app.schemas.user import UpdateRoleRequest
from app.schemas.user import User as UserOut

router = APIRouter(prefix="/users", tags=["users"])

_USER_NOT_FOUND_DETAIL = "No user exists with this id."
_LAST_ADMIN_DETAIL = "Cannot demote the last admin."


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

    if target.role == Role.ADMIN.value and payload.role == Role.MEMBER:
        admin_count = await db.scalar(
            select(func.count()).select_from(User).where(User.role == Role.ADMIN.value)
        )
        if (admin_count or 0) <= 1:
            raise ProblemDetailError(403, ErrorCode.FORBIDDEN, _LAST_ADMIN_DETAIL)

    target.role = payload.role.value
    return target
