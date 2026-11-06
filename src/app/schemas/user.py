"""User response schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import Role


class User(BaseModel):
    """The public representation of a user (never the password hash)."""

    id: str
    name: str
    email: EmailStr
    role: Role
    created_at: datetime = Field(serialization_alias="createdAt")
