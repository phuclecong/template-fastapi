"""Task endpoints: create and get single (POST /tasks, GET /tasks/{id})."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.models.task import Status, Task
from app.models.user import User
from app.schemas.task import Task as TaskOut
from app.schemas.task import TaskCreateRequest

router = APIRouter(prefix="/tasks", tags=["tasks"])

_TASK_NOT_FOUND_DETAIL = "No task exists with this id."
_BORN_DONE_DETAIL = "A task cannot be created with status done."
_ASSIGNEE_NOT_FOUND_DETAIL = "No user exists with the given assigneeId."


@router.post("", status_code=201, response_model=TaskOut)
async def create_task(
    payload: TaskCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Create a task (never ``done`` at birth)."""
    if payload.status == Status.DONE:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _BORN_DONE_DETAIL)

    if payload.assignee_id is not None:
        assignee = await db.scalar(select(User).where(User.id == payload.assignee_id))
        if assignee is None:
            raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _ASSIGNEE_NOT_FOUND_DETAIL)

    task = Task(
        title=payload.title,
        description=payload.description,
        status=payload.status.value,
        priority=payload.priority.value if payload.priority is not None else None,
        assignee_id=payload.assignee_id,
        due_date=payload.due_date,
    )
    db.add(task)
    await db.flush()
    return task


@router.get("/{id}", response_model=TaskOut)
async def get_task(
    id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Return a task by id, or 404."""
    task = await db.get(Task, id)
    if task is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _TASK_NOT_FOUND_DETAIL)
    return task
