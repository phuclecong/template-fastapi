"""Live events endpoint: an SSE invalidation stream (GET /events)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.dependencies import INVALID_ACCESS_TOKEN_DETAIL
from app.core.database import get_session_factory
from app.core.errors import ErrorCode, ProblemDetailError
from app.core.events import TASKS_CHANNEL, encode_live_event, live_event_bus
from app.core.security import decode_access_token
from app.models.user import User

router = APIRouter(tags=["events"])

_SUPPORTED_CHANNELS = frozenset({TASKS_CHANNEL})
_UNKNOWN_CHANNEL_DETAIL = "Unknown channel."
_KEEPALIVE_SECONDS = 15.0
_CONNECTED_COMMENT = b": connected\n\n"
_KEEPALIVE_COMMENT = b": ping\n\n"


async def get_stream_user(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    access_token: Annotated[str | None, Query()] = None,
) -> User:
    """Resolve the stream's user from ``access_token``, an ``EventSource`` limitation.

    The browser's ``EventSource`` cannot set an ``Authorization`` header, so the
    access token travels in the query string instead of the usual Bearer header.
    The session is closed before streaming starts so an open stream never pins a
    database connection.
    """
    if not access_token:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL)
    try:
        payload = decode_access_token(access_token)
    except InvalidTokenError:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL) from None

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL)

    async with session_factory() as session:
        user = await session.get(User, user_id)
    if user is None:
        raise ProblemDetailError(401, ErrorCode.UNAUTHORIZED, INVALID_ACCESS_TOKEN_DETAIL)
    return user


@router.get(
    "/events",
    operation_id="streamEvents",
    responses={
        200: {
            "description": "A Server-Sent Events stream of `live` invalidation events.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream_events(
    channel: Annotated[str, Query()],
    _current_user: Annotated[User, Depends(get_stream_user)],
) -> StreamingResponse:
    """Stream invalidation events for ``channel`` until the client disconnects."""
    if channel not in _SUPPORTED_CHANNELS:
        raise ProblemDetailError(422, ErrorCode.VALIDATION_ERROR, _UNKNOWN_CHANNEL_DETAIL)

    return StreamingResponse(
        _event_stream(channel),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _event_stream(channel: str) -> AsyncGenerator[bytes, None]:
    """Yield SSE frames for ``channel``, with periodic comments to keep proxies open."""
    queue = live_event_bus.subscribe(channel)
    try:
        yield _CONNECTED_COMMENT
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
            except TimeoutError:
                yield _KEEPALIVE_COMMENT
                continue
            yield encode_live_event(event)
    finally:
        live_event_bus.unsubscribe(channel, queue)
