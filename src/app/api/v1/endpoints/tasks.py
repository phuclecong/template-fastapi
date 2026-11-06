"""Task endpoints: list, create, get single, update, delete (GET/POST/PATCH/DELETE /tasks)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import FORBIDDEN_DETAIL, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.models.task import Priority, Status, Task
from app.models.user import Role, User
from app.schemas.task import (
    BulkFailure,
    TaskBulkUpdateRequest,
    TaskBulkUpdateResponse,
    TaskCreateRequest,
    TaskUpdateRequest,
)
from app.schemas.task import Task as TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])

_TASK_NOT_FOUND_DETAIL = "No task exists with this id."
_BORN_DONE_DETAIL = "A task cannot be created with status done."
_ASSIGNEE_NOT_FOUND_DETAIL = "No user exists with the given assigneeId."
_INVALID_STATUS_TRANSITION_DETAIL = "Invalid status transition."
_INVALID_SORT_FIELD_DETAIL = "Unknown sort field."

# Sort order is the spec's declared order (docs/openapi.yaml §Status/§Priority), not
# alphabetical and not the enum declaration order — keep them literal.
_STATUS_SORT_ORDER = {"todo": 0, "in-progress": 1, "done": 2, "blocked": 3}
_PRIORITY_SORT_ORDER = {"low": 0, "medium": 1, "high": 2}

_SORT_KEYS: dict[str, Any] = {
    "title": Task.title,
    "status": case(_STATUS_SORT_ORDER, value=Task.status, else_=len(_STATUS_SORT_ORDER)),
    "priority": case(_PRIORITY_SORT_ORDER, value=Task.priority, else_=len(_PRIORITY_SORT_ORDER)),
    "dueDate": Task.due_date,
}


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so ``q`` matches a literal substring, not a pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str | None, Query()] = None,
    status: Annotated[Status | None, Query()] = None,
    priority: Annotated[Priority | None, Query()] = None,
    assignee_id: Annotated[str | None, Query(alias="assigneeId")] = None,
    due_date_gte: Annotated[date | None, Query(alias="dueDate_gte")] = None,
    due_date_lte: Annotated[date | None, Query(alias="dueDate_lte")] = None,
    _start: Annotated[int, Query(ge=0)] = 0,
    _end: Annotated[int | None, Query(ge=0)] = None,
    _sort: Annotated[str, Query()] = "title",
    _order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> list[Task]:
    """Return tasks filtered, sorted, and paginated, with the total in ``x-total-count``."""
    conditions: list[Any] = []
    if q is not None:
        conditions.append(Task.title.ilike(f"%{_escape_like(q)}%", escape="\\"))
    if status is not None:
        conditions.append(Task.status == status.value)
    if priority is not None:
        conditions.append(Task.priority == priority.value)
    if assignee_id is not None:
        if assignee_id == "unassigned":
            conditions.append(Task.assignee_id.is_(None))
        else:
            conditions.append(Task.assignee_id == assignee_id)
    if due_date_gte is not None:
        conditions.append(Task.due_date >= due_date_gte)
    if due_date_lte is not None:
        conditions.append(Task.due_date <= due_date_lte)

    total = await db.scalar(select(func.count()).select_from(Task).where(*conditions))

    sort_key = _SORT_KEYS.get(_sort)
    if sort_key is None:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_SORT_FIELD_DETAIL)
    order = sort_key.asc() if _order == "asc" else sort_key.desc()

    statement = select(Task).where(*conditions).order_by(order, Task.id).offset(_start)
    if _end is not None:
        statement = statement.limit(max(0, _end - _start))

    tasks = list((await db.scalars(statement)).all())
    response.headers["x-total-count"] = str(total or 0)
    return tasks


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


@router.patch("/bulk", response_model=TaskBulkUpdateResponse)
async def bulk_update_tasks(
    payload: TaskBulkUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskBulkUpdateResponse:
    """Update status/priority/assignee across many tasks; per-id failures are reported.

    A task is updated as a unit: it either applies all requested fields or is reported
    in ``failed`` with a reason (not found, forbidden, or an invalid status transition).
    """
    if payload.assignee_id is not None:
        await _require_assignee(db, payload.assignee_id)

    updated = 0
    failed: list[BulkFailure] = []
    seen: set[str] = set()

    for task_id in payload.ids:
        if task_id in seen:
            continue
        seen.add(task_id)

        task = await db.get(Task, task_id)
        if task is None:
            failed.append(BulkFailure(id=task_id, reason=_TASK_NOT_FOUND_DETAIL))
            continue

        if current_user.role != Role.ADMIN.value and task.assignee_id != current_user.id:
            failed.append(BulkFailure(id=task_id, reason=FORBIDDEN_DETAIL))
            continue

        try:
            if "status" in payload.model_fields_set and payload.status is not None:
                _apply_status_transition(task, payload.status)
            if "priority" in payload.model_fields_set:
                task.priority = payload.priority.value if payload.priority is not None else None
            if "assignee_id" in payload.model_fields_set:
                task.assignee_id = payload.assignee_id
        except ProblemDetailError as exc:
            failed.append(BulkFailure(id=task_id, reason=exc.detail))
            continue

        updated += 1

    await db.flush()
    return TaskBulkUpdateResponse(updated=updated, failed=failed)


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
