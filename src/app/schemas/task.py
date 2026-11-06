"""Task request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.models.task import Priority, Status
from app.models.user import ensure_utc


class Task(BaseModel):
    """The public representation of a task."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None = None
    status: Status
    priority: Priority | None = None
    assignee_id: str | None = Field(default=None, serialization_alias="assigneeId")
    due_date: date | None = Field(default=None, serialization_alias="dueDate")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetimes(self, value: datetime) -> datetime:
        # SQLite reads DateTime back naive; normalize so every endpoint emits UTC.
        return ensure_utc(value)


class TaskCreateRequest(BaseModel):
    """Body of POST /tasks."""

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: Status = Status.TODO
    priority: Priority | None = None
    assignee_id: str | None = Field(default=None, validation_alias="assigneeId")
    due_date: date | None = Field(default=None, validation_alias="dueDate")


class TaskUpdateRequest(BaseModel):
    """Body of PATCH /tasks/{id}; omitted fields are unchanged, explicit null clears."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: Status | None = None
    priority: Priority | None = None
    assignee_id: str | None = Field(default=None, validation_alias="assigneeId")
    due_date: date | None = Field(default=None, validation_alias="dueDate")

    @model_validator(mode="after")
    def _reject_null_for_non_nullable_fields(self) -> TaskUpdateRequest:
        """``title`` and ``status`` are not nullable per the contract, unlike the
        clearable fields (description, priority, assigneeId, dueDate)."""
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self
