"""Registration endpoint (POST /auth/register)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
)
from app.models.session import Session
from app.models.user import Role, User, normalize_email, utcnow
from app.schemas.auth import AuthResponse, RegisterRequest
from app.schemas.user import User as UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_DUPLICATE_EMAIL_DETAIL = "A user with this email already exists."


@router.post("/register", status_code=201, response_model=AuthResponse)
async def register(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
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
        user=UserOut(
            id=user.id,
            name=user.name,
            email=user.email,
            role=Role(user.role),
            created_at=user.created_at,
        ),
    )
