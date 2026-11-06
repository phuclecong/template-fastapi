"""Authentication request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.core.security import MIN_PASSWORD_LENGTH
from app.schemas.user import User


class RegisterRequest(BaseModel):
    """Body of POST /auth/register."""

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class AuthResponse(BaseModel):
    """Access + refresh tokens, plus the authenticated user."""

    accessToken: str
    refreshToken: str
    user: User
