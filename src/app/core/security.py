"""Password hashing (Argon2id) and token primitives (JWT access + opaque refresh)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

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


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if ``password`` matches the Argon2id ``password_hash``."""
    try:
        return _password_hasher.verify(password_hash, password)
    except Argon2Error:
        return False


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


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an access token JWT (raises ``jwt.InvalidTokenError``)."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for server-side storage."""
    return hashlib.sha256(token.encode()).hexdigest()
