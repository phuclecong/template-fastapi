"""Dashboard endpoint: a workspace-wide Task summary (GET /dashboard/summary)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.time import utcnow
from app.models.task import Priority, Status, Task
from app.models.user import User
from app.schemas.dashboard import (
    DashboardAssigneeCount,
    DashboardPriorityCount,
    DashboardStatusCount,
    DashboardSummary,
    DashboardTotals,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Stable chart shapes: the contract's declared order, never alphabetical.
_STATUS_ORDER = (Status.TODO, Status.IN_PROGRESS, Status.DONE, Status.BLOCKED)
_PRIORITY_ORDER = (Priority.LOW, Priority.MEDIUM, Priority.HIGH)
_UNASSIGNED: Literal["unassigned"] = "unassigned"
_TOP_ASSIGNEES = 5


@router.get("/summary", response_model=DashboardSummary, operation_id="getDashboardSummary")
async def get_dashboard_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> DashboardSummary:
    """Return totals, distributions, and the busiest assignees for the whole board."""
    now = utcnow()

    status_rows = (await db.execute(select(Task.status, func.count()).group_by(Task.status))).all()
    status_counts = {str(status): count for status, count in status_rows}

    total = sum(status_counts.values())
    done = status_counts.get(Status.DONE.value, 0)
    open_tasks = total - done

    overdue = (
        await db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.status != Status.DONE.value,
                Task.due_date.is_not(None),
                Task.due_date < now,
            )
        )
    ) or 0
    completion_rate = done / total if total else 0.0

    priority_rows = (
        await db.execute(select(Task.priority, func.count()).group_by(Task.priority))
    ).all()
    priority_counts = {priority: count for priority, count in priority_rows}

    assignee_rows = (
        await db.execute(
            select(Task.assignee_id, User.name, func.count().label("task_count"))
            .join(User, User.id == Task.assignee_id)
            .group_by(Task.assignee_id, User.name)
            .order_by(
                func.count().desc(),
                User.name.asc(),
                Task.assignee_id.asc(),
            )
            .limit(_TOP_ASSIGNEES)
        )
    ).all()
    unassigned_count = (
        await db.scalar(select(func.count()).select_from(Task).where(Task.assignee_id.is_(None)))
    ) or 0

    by_assignee = [
        DashboardAssigneeCount(assignee_id=assignee_id, name=name, count=count)
        for assignee_id, name, count in assignee_rows
    ]
    if unassigned_count:
        by_assignee.append(
            DashboardAssigneeCount(assignee_id=None, name="", count=unassigned_count)
        )

    by_priority = [
        DashboardPriorityCount(
            priority=priority.value, count=priority_counts.get(priority.value, 0)
        )
        for priority in _PRIORITY_ORDER
    ]
    by_priority.append(
        DashboardPriorityCount(priority=_UNASSIGNED, count=priority_counts.get(None, 0))
    )

    return DashboardSummary(
        totals=DashboardTotals(
            total=total,
            open=open_tasks,
            overdue=overdue,
            completion_rate=completion_rate,
        ),
        by_status=[
            DashboardStatusCount(status=status, count=status_counts.get(status.value, 0))
            for status in _STATUS_ORDER
        ],
        by_priority=by_priority,
        by_assignee=by_assignee,
        generated_at=now,
    )
