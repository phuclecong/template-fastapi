"""Password hashing (Argon2id) and token primitives (JWT access + opaque refresh)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher

from app.core.config import get_settings

MIN_PASSWORD_LENGTH = 8

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _password_hasher.hash(password)


def validate_password(password: str) -> None:
    """Raise ValueError if the password is shorter than the minimum length."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


def create_access_token(*, sub: str, session_id: str) -> str:
    """Encode a JWT access token carrying the user id and session id."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "sid": session_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def generate_refresh_token() -> str:
    """Generate an opaque refresh token."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for server-side storage."""
    return hashlib.sha256(token.encode()).hexdigest()
