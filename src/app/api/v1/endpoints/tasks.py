"""Task endpoints: list, create, get single, update, delete (GET/POST/PATCH/DELETE /tasks)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import FORBIDDEN_DETAIL, get_current_user
from app.core.database import get_db
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.text import escape_like
from app.core.time import to_utc
from app.models.task import Priority, Status, Task
from app.models.user import User
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


def _validated_values(values: list[str] | None, allowed: set[str], field: str) -> list[str]:
    """Drop empty repeats and reject values outside ``allowed`` as malformed (422)."""
    cleaned = [value for value in (values or []) if value != ""]
    for value in cleaned:
        if value not in allowed:
            raise ProblemDetailError(
                422, ErrorCode.VALIDATION_ERROR, f"Invalid {field} value: {value}."
            )
    return cleaned


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


def _is_assignee_or_admin(task: Task, user: User) -> bool:
    """Return True if ``user`` is an Administrator or the task's assignee."""
    return user.is_administrator or task.assignee_id == user.id


def _ensure_assignee_or_admin(task: Task, user: User) -> None:
    """Raise 403 unless ``user`` is an admin or the task's assignee."""
    if not _is_assignee_or_admin(task, user):
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


@router.get("", response_model=list[TaskOut], operation_id="listTasks")
async def list_tasks(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    priority: Annotated[list[str] | None, Query()] = None,
    assignee_id: Annotated[list[str] | None, Query(alias="assigneeId")] = None,
    due_date_gte: Annotated[AwareDatetime | None, Query(alias="dueDate_gte")] = None,
    due_date_lte: Annotated[AwareDatetime | None, Query(alias="dueDate_lte")] = None,
    _start: Annotated[int, Query(ge=0)] = 0,
    _end: Annotated[int | None, Query(ge=0)] = None,
    _sort: Annotated[str, Query()] = "title",
    _order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> list[Task]:
    """Return tasks filtered, sorted, and paginated, with the total in ``x-total-count``."""
    conditions: list[Any] = []
    if q is not None:
        conditions.append(Task.title.ilike(f"%{escape_like(q)}%", escape="\\"))
    statuses = _validated_values(status, {value.value for value in Status}, "status")
    if statuses:
        conditions.append(Task.status.in_(statuses))
    priorities = _validated_values(priority, {value.value for value in Priority}, "priority")
    if priorities:
        conditions.append(Task.priority.in_(priorities))
    assignees = [value for value in (assignee_id or []) if value != ""]
    if assignees:
        # ``unassigned`` matches a null Assignee; other values must be existing Users.
        user_ids = list(dict.fromkeys(value for value in assignees if value != "unassigned"))
        if user_ids:
            existing = set((await db.scalars(select(User.id).where(User.id.in_(user_ids)))).all())
            if any(user_id not in existing for user_id in user_ids):
                raise ProblemDetailError(
                    400, ErrorCode.VALIDATION_ERROR, _ASSIGNEE_NOT_FOUND_DETAIL
                )
        assignee_conditions: list[Any] = []
        if user_ids:
            assignee_conditions.append(Task.assignee_id.in_(user_ids))
        if "unassigned" in assignees:
            assignee_conditions.append(Task.assignee_id.is_(None))
        conditions.append(or_(*assignee_conditions))
    if due_date_gte is not None:
        conditions.append(Task.due_date >= to_utc(due_date_gte))
    if due_date_lte is not None:
        conditions.append(Task.due_date <= to_utc(due_date_lte))

    total = await db.scalar(select(func.count()).select_from(Task).where(*conditions))

    sort_key = _SORT_KEYS.get(_sort)
    if sort_key is None:
        raise ProblemDetailError(400, ErrorCode.VALIDATION_ERROR, _INVALID_SORT_FIELD_DETAIL)
    if _sort == "dueDate":
        # Nulls always sort last, regardless of direction.
        order = sort_key.asc().nulls_last() if _order == "asc" else sort_key.desc().nulls_last()
    else:
        order = sort_key.asc() if _order == "asc" else sort_key.desc()

    statement = select(Task).where(*conditions).order_by(order, Task.id).offset(_start)
    if _end is not None:
        statement = statement.limit(max(0, _end - _start))

    tasks = list((await db.scalars(statement)).all())
    response.headers["x-total-count"] = str(total or 0)
    return tasks


@router.post("", status_code=201, response_model=TaskOut, operation_id="createTask")
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
        due_date=to_utc(payload.due_date),
    )
    db.add(task)
    await db.flush()
    return task


@router.patch("/bulk", response_model=TaskBulkUpdateResponse, operation_id="bulkUpdateTasks")
async def bulk_update_tasks(
    payload: TaskBulkUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskBulkUpdateResponse:
    """Update status/priority/assignee/due date across many tasks; per-id failures are reported.

    A task is updated as a unit: it either applies all requested fields or is reported
    in ``failed`` with a reason (not found, forbidden, or an invalid status transition).
    """
    updated = 0
    failed: list[BulkFailure] = []
    updatable: list[Task] = []
    seen: set[str] = set()

    for task_id in payload.ids:
        # A repeated id is updated (and counted) once; the contract leaves this undefined.
        if task_id in seen:
            continue
        seen.add(task_id)

        task = await db.get(Task, task_id)
        if task is None:
            failed.append(BulkFailure(id=task_id, reason=_TASK_NOT_FOUND_DETAIL))
            continue

        if not _is_assignee_or_admin(task, current_user):
            failed.append(BulkFailure(id=task_id, reason=FORBIDDEN_DETAIL))
            continue

        updatable.append(task)

    # Validate the assignee only when it will actually be applied to a task the caller
    # can touch, mirroring single-PATCH (ownership is checked before assignee existence).
    if payload.assignee_id is not None and updatable:
        await _require_assignee(db, payload.assignee_id)

    for task in updatable:
        try:
            if "status" in payload.model_fields_set and payload.status is not None:
                _apply_status_transition(task, payload.status)
            if "priority" in payload.model_fields_set:
                task.priority = payload.priority.value if payload.priority is not None else None
            if "assignee_id" in payload.model_fields_set:
                task.assignee_id = payload.assignee_id
            if "due_date" in payload.model_fields_set:
                task.due_date = to_utc(payload.due_date)
        except ProblemDetailError as exc:
            failed.append(BulkFailure(id=task.id, reason=exc.detail))
            continue

        updated += 1

    await db.flush()
    return TaskBulkUpdateResponse(updated=updated, failed=failed)


@router.get("/{id}", response_model=TaskOut, operation_id="getTask")
async def get_task(
    id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Return a task by id, or 404."""
    return await _get_task_or_404(db, id)


@router.patch("/{id}", response_model=TaskOut, operation_id="updateTask")
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
        task.due_date = to_utc(payload.due_date)
    if "assignee_id" in fields:
        if payload.assignee_id is not None:
            await _require_assignee(db, payload.assignee_id)
        task.assignee_id = payload.assignee_id
    if "status" in fields and payload.status is not None:
        _apply_status_transition(task, payload.status)

    await db.flush()
    return task


@router.delete("/{id}", status_code=204, operation_id="deleteTask")
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
