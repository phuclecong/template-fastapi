"""Authentication endpoints: register, login, refresh, logout (POST /auth/*)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import enforce_rate_limit, get_current_session_id
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.session import Session
from app.models.user import Role, User, ensure_utc, normalize_email, utcnow
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
)
from app.schemas.user import User as UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_DUPLICATE_EMAIL_DETAIL = "A user with this email already exists."
_INVALID_CREDENTIALS_DETAIL = "Invalid email or password."
_INVALID_REFRESH_TOKEN_DETAIL = "Invalid refresh token."
_REFRESH_REUSE_DETAIL = "Refresh token reuse detected; session revoked."


async def _issue_session_tokens(db: AsyncSession, user: User) -> AuthResponse:
    """Create a session for ``user`` and return its tokens plus the user."""
    refresh_token = generate_refresh_token()
    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        expires_at=utcnow() + timedelta(days=get_settings().refresh_token_expire_days),
    )
    db.add(session)
    await db.flush()

    access_token = create_access_token(sub=user.id, session_id=session.id)

    return AuthResponse(
        accessToken=access_token,
        refreshToken=refresh_token,
        user=UserOut.model_validate(user),
    )


@router.post("/register", status_code=201, response_model=AuthResponse)
async def register(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit)],
) -> AuthResponse:
    """Create a user (role ``member``) and start a session."""
    email = normalize_email(payload.email)

    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ProblemDetailError(409, ErrorCode.CONFLICT, _DUPLICATE_EMAIL_DETAIL)

    user = User(
        name=payload.name,
        email=email,
        hashed_password=hash_password(payload.password),
        role=Role.MEMBER.value,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Backstop for the unique-email constraint under concurrent registration.
        raise ProblemDetailError(409, ErrorCode.CONFLICT, _DUPLICATE_EMAIL_DETAIL) from None

    return await _issue_session_tokens(db, user)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit)],
) -> AuthResponse:
    """Start a session for a user with valid email + password."""
    email = normalize_email(payload.email)

    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, _INVALID_CREDENTIALS_DETAIL)

    return await _issue_session_tokens(db, user)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    payload: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit)],
) -> RefreshResponse:
    """Rotate a refresh token; presenting a stale (already-rotated) one revokes the session."""
    presented_hash = hash_refresh_token(payload.refreshToken)

    session = await db.scalar(
        select(Session).where(
            or_(
                Session.refresh_token_hash == presented_hash,
                Session.previous_refresh_token_hash == presented_hash,
            )
        )
    )
    if session is None:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, _INVALID_REFRESH_TOKEN_DETAIL)

    now = utcnow()
    if session.revoked_at is not None or ensure_utc(session.expires_at) <= now:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, _INVALID_REFRESH_TOKEN_DETAIL)

    if session.previous_refresh_token_hash == presented_hash:
        # Reuse of an already-rotated token: revoke the whole session. Commit before
        # raising so the revocation survives get_db's rollback-on-error.
        session.revoked_at = now
        await db.commit()
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, _REFRESH_REUSE_DETAIL)

    new_refresh_token = generate_refresh_token()
    session.previous_refresh_token_hash = session.refresh_token_hash
    session.refresh_token_hash = hash_refresh_token(new_refresh_token)
    session.expires_at = now + timedelta(days=get_settings().refresh_token_expire_days)

    access_token = create_access_token(sub=session.user_id, session_id=session.id)

    return RefreshResponse(accessToken=access_token, refreshToken=new_refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    session_id: Annotated[str, Depends(get_current_session_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Revoke the session identified by the access token (idempotent)."""
    session = await db.get(Session, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
    return Response(status_code=204)
