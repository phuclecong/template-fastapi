"""Task endpoints: create, get single, update, delete (POST/GET/PATCH/DELETE /tasks)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import FORBIDDEN_DETAIL, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.models.task import Status, Task
from app.models.user import Role, User
from app.schemas.task import Task as TaskOut
from app.schemas.task import TaskCreateRequest, TaskUpdateRequest

router = APIRouter(prefix="/tasks", tags=["tasks"])

_TASK_NOT_FOUND_DETAIL = "No task exists with this id."
_BORN_DONE_DETAIL = "A task cannot be created with status done."
_ASSIGNEE_NOT_FOUND_DETAIL = "No user exists with the given assigneeId."
_INVALID_STATUS_TRANSITION_DETAIL = "Invalid status transition."


async def _get_task_or_404(db: AsyncSession, task_id: str) -> Task:
    """Return the task with ``task_id``, or raise 404."""
    task = await db.get(Task, task_id)
    if task is None:
        raise ProblemDetailError(404, ErrorCode.NOT_FOUND, _TASK_NOT_FOUND_DETAIL)
    return task


async def _require_assignee(db: AsyncSession, assignee_id: str) -> None:
    """Raise 400 if no user has ``assignee_id``."""
    assignee = await db.scalar(select(User).where(User.id == assignee_id))
    if assignee is None:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _ASSIGNEE_NOT_FOUND_DETAIL)


def _ensure_assignee_or_admin(task: Task, user: User) -> None:
    """Raise 403 unless ``user`` is an admin or the task's assignee."""
    if user.role == Role.ADMIN.value or task.assignee_id == user.id:
        return
    raise ProblemDetailError(403, ErrorCode.FORBIDDEN, FORBIDDEN_DETAIL)


def _apply_status_transition(task: Task, new_status: Status) -> None:
    """Move ``task`` to ``new_status`` under the status machine, or raise 400.

    Forward path is ``todo -> in-progress -> done``; ``blocked`` is a pause entered
    from ``todo``/``in-progress`` that records the prior state and, on unblock,
    restores it (see GLOSSARY and spec §Domain).
    """
    current = task.status
    new = new_status.value

    if new == current:
        return

    if new == Status.BLOCKED.value:
        if current in (Status.TODO.value, Status.IN_PROGRESS.value):
            task.previous_status = current
            task.status = new
            return
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_STATUS_TRANSITION_DETAIL)

    if current == Status.BLOCKED.value:
        # Unblocking returns to the prior state; done is never reachable from blocked.
        if new == Status.DONE.value or task.previous_status is None:
            raise ProblemDetailError(
                400, ErrorCode.VALIDATION_ERROR, _INVALID_STATUS_TRANSITION_DETAIL
            )
        task.status = task.previous_status
        task.previous_status = None
        return

    if current == Status.TODO.value and new == Status.IN_PROGRESS.value:
        task.status = new
        return
    if current == Status.IN_PROGRESS.value and new == Status.DONE.value:
        task.status = new
        return

    raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_STATUS_TRANSITION_DETAIL)


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
        await _require_assignee(db, payload.assignee_id)

    task = Task(
        title=payload.title,
        description=payload.description,
        status=payload.status.value,
        # A task born blocked has no prior state; unblocking resumes from ``todo``.
        previous_status=Status.TODO.value if payload.status == Status.BLOCKED else None,
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
    return await _get_task_or_404(db, id)


@router.patch("/{id}", response_model=TaskOut)
async def update_task(
    id: str,
    payload: TaskUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Update a task (assignee or admin); omitted fields are unchanged, null clears."""
    task = await _get_task_or_404(db, id)

    _ensure_assignee_or_admin(task, current_user)

    fields = payload.model_fields_set

    if "title" in fields and payload.title is not None:
        task.title = payload.title
    if "description" in fields:
        task.description = payload.description
    if "priority" in fields:
        task.priority = payload.priority.value if payload.priority is not None else None
    if "due_date" in fields:
        task.due_date = payload.due_date
    if "assignee_id" in fields:
        if payload.assignee_id is not None:
            await _require_assignee(db, payload.assignee_id)
        task.assignee_id = payload.assignee_id
    if "status" in fields and payload.status is not None:
        _apply_status_transition(task, payload.status)

    await db.flush()
    return task


@router.delete("/{id}", status_code=204)
async def delete_task(
    id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Delete a task (assignee or admin)."""
    task = await _get_task_or_404(db, id)

    _ensure_assignee_or_admin(task, current_user)

    await db.delete(task)
    return Response(status_code=204)
