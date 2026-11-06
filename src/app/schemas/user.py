"""User request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer

from app.models.user import Role, ensure_utc


class User(BaseModel):
    """The public representation of a user (never the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: EmailStr
    role: Role
    created_at: datetime = Field(serialization_alias="createdAt")

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        # SQLite reads DateTime back naive; normalize so every endpoint emits UTC.
        return ensure_utc(value)


class UpdateRoleRequest(BaseModel):
    """Body of PATCH /users/{id}/role."""

    role: Role
