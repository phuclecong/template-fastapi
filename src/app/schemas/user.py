"""User request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_serializer,
    model_validator,
)

from app.core.time import ensure_utc
from app.models.role import RoleStatus


class RoleSummary(BaseModel):
    """The Role identity and display summary embedded in a User."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: RoleStatus


class User(BaseModel):
    """The public representation of a user (never the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: EmailStr
    role_id: str = Field(serialization_alias="roleId")
    role: RoleSummary
    created_at: datetime = Field(serialization_alias="createdAt")

    @model_validator(mode="before")
    @classmethod
    def _embed_role_summary(cls, data: Any) -> Any:
        """Build the embedded Role summary from the ORM relationship.

        A User whose Role row no longer exists (a referential gap) degrades to a
        summary derived from the id instead of raising a 500.
        """
        if isinstance(data, dict):
            return data
        role_id = getattr(data, "role_id", None)
        if role_id is None:
            return data

        role = getattr(data, "role", None)
        if role is None:
            summary: dict[str, Any] = {
                "id": role_id,
                "title": role_id,
                "status": RoleStatus.ACTIVE.value,
            }
        else:
            summary = {"id": role.id, "title": role.title, "status": role.status}

        return {
            "id": data.id,
            "name": data.name,
            "email": data.email,
            "role_id": role_id,
            "role": summary,
            "created_at": data.created_at,
        }

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        # SQLite reads DateTime back naive; normalize so every endpoint emits UTC.
        return ensure_utc(value)


class UpdateRoleRequest(BaseModel):
    """Body of PATCH /users/{id}/role."""

    role_id: str = Field(validation_alias="roleId")
