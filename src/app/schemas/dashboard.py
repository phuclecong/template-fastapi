"""Dashboard response schemas: the workspace-wide Task summary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.task import Status


class DashboardTotals(BaseModel):
    """Board-wide Task totals and completion rate."""

    total: int
    open: int
    overdue: int
    completion_rate: float = Field(serialization_alias="completionRate")


class DashboardStatusCount(BaseModel):
    """How many Tasks sit in one lifecycle status."""

    status: Status
    count: int


class DashboardPriorityCount(BaseModel):
    """How many Tasks carry one priority (or no priority, as ``unassigned``)."""

    priority: Literal["low", "medium", "high", "unassigned"]
    count: int


class DashboardAssigneeCount(BaseModel):
    """How many Tasks one assignee holds; the Unassigned bucket has no id or name."""

    assignee_id: str | None = Field(serialization_alias="assigneeId")
    name: str
    count: int


class DashboardSummary(BaseModel):
    """The aggregate Task counts the Dashboard renders."""

    totals: DashboardTotals
    by_status: list[DashboardStatusCount] = Field(serialization_alias="byStatus")
    by_priority: list[DashboardPriorityCount] = Field(serialization_alias="byPriority")
    by_assignee: list[DashboardAssigneeCount] = Field(serialization_alias="byAssignee")
    generated_at: datetime = Field(serialization_alias="generatedAt")
