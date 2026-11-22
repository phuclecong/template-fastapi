"""Role request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.time import ensure_utc
from app.models.role import RoleStatus
from app.schemas.common import reject_null_for_non_nullable_fields


class Role(BaseModel):
    """The public representation of a Role."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None = None
    status: RoleStatus
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetimes(self, value: datetime) -> datetime:
        # SQLite reads DateTime back naive; normalize so every endpoint emits UTC.
        return ensure_utc(value)


def _trim_title(value: Any) -> Any:
    """Trim a title before its length constraints are checked."""
    return value.strip() if isinstance(value, str) else value


def _trim_description(value: Any) -> Any:
    """Trim a description before its length constraints; a blank value becomes null."""
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    return trimmed or None


class RoleCreateRequest(BaseModel):
    """Body of POST /roles; the title is trimmed and required, status defaults to active."""

    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: RoleStatus = RoleStatus.ACTIVE

    _trim_title = field_validator("title", mode="before")(_trim_title)
    _trim_description = field_validator("description", mode="before")(_trim_description)


class RoleUpdateRequest(BaseModel):
    """Body of PATCH /roles/{id}; omitted fields are unchanged, explicit null clears."""

    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    status: RoleStatus | None = None

    _trim_title = field_validator("title", mode="before")(_trim_title)
    _trim_description = field_validator("description", mode="before")(_trim_description)

    @model_validator(mode="after")
    def _reject_null_for_non_nullable_fields(self) -> RoleUpdateRequest:
        """``title`` and ``status`` are not nullable per the contract; description is."""
        reject_null_for_non_nullable_fields(self, "title", "status")
        return self


BulkFailureReason = Literal["not_found", "system_role", "referenced", "validation"]


class RoleBulkFailure(BaseModel):
    """A single Role id that a bulk operation did not apply, and the reason."""

    id: str
    reason: BulkFailureReason


class RoleBulkUpdateResponse(BaseModel):
    """Result of PATCH /roles/bulk: how many Roles updated, plus per-id failures."""

    updated: int
    failed: list[RoleBulkFailure]


class RoleBulkDeleteResponse(BaseModel):
    """Result of POST /roles/bulk-delete: how many Roles deleted, plus per-id failures."""

    deleted: int
    failed: list[RoleBulkFailure]
