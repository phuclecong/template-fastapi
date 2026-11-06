"""Shared FastAPI dependencies: bearer-token authentication and role guards."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.security import decode_access_token
from app.models.user import Role, User

INVALID_ACCESS_TOKEN_DETAIL = "Invalid or expired access token."
FORBIDDEN_DETAIL = "You do not have permission to perform this action."

_bearer = HTTPBearer(auto_error=False)


def _require_claim(payload: dict[str, Any], key: str) -> str:
    """Return the non-empty string claim ``key`` from the token payload, else 401."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL)
    return value


async def get_access_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any]:
    """Decode the bearer access token into its JWT payload, or raise 401."""
    if credentials is None:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL)
    try:
        return decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL) from None


async def get_current_user(
    payload: Annotated[dict[str, Any], Depends(get_access_token_payload)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the authenticated user from the access token's subject."""
    user_id = _require_claim(payload, "sub")
    user = await db.get(User, user_id)
    if user is None:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL)
    return user


async def get_current_session_id(
    payload: Annotated[dict[str, Any], Depends(get_access_token_payload)],
) -> str:
    """Resolve the session id from the bearer access token, or raise 401."""
    return _require_claim(payload, "sid")


async def get_current_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Resolve the authenticated admin, or raise 403."""
    if user.role != Role.ADMIN.value:
        raise ProblemDetailError(403, ErrorCode.FORBIDDEN, FORBIDDEN_DETAIL)
    return user
