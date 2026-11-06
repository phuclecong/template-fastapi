"""Password endpoint: change the authenticated user's password (PUT /password)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_session_id, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.security import hash_password, verify_password
from app.models.session import Session
from app.models.user import User, utcnow
from app.schemas.auth import PasswordUpdateRequest

router = APIRouter(tags=["password"])

_WRONG_CURRENT_PASSWORD_DETAIL = "Current password is incorrect."


@router.put("/password", status_code=204)
async def update_password(
    payload: PasswordUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    session_id: Annotated[str, Depends(get_current_session_id)],
) -> Response:
    """Change the authenticated user's password; revoke every other session."""
    if not verify_password(payload.currentPassword, current_user.hashed_password):
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _WRONG_CURRENT_PASSWORD_DETAIL)

    current_user.hashed_password = hash_password(payload.newPassword)

    await db.execute(
        update(Session)
        .where(
            Session.user_id == current_user.id,
            Session.id != session_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )

    return Response(status_code=204)
