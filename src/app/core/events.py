"""In-process Live event bus and SSE wire encoding.

The frontend's `EventSource` listens on a resource channel (for example
``resources/tasks``) and treats each event as an invalidation signal: the payload
carries ids only, and the client refetches the authoritative data. This module owns
the fan-out from mutation endpoints to connected streams. It is deliberately
in-process: the template runs a single API process, so a broker (Redis pub/sub,
Postgres LISTEN/NOTIFY) is out of scope. A multi-process deployment would need one.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.time import utcnow

TASKS_CHANNEL = "resources/tasks"

EventType = Literal["created", "updated", "deleted"]

# A stalled client gets the oldest event dropped rather than growing memory without
# bound. Events are invalidation signals, so the next event or refetch heals the gap.
_MAX_QUEUE_SIZE = 256


@dataclass(frozen=True, slots=True)
class LiveEvent:
    """An invalidation signal for one resource channel."""

    channel: str
    type: EventType
    ids: tuple[str, ...]
    date: datetime


class LiveEventBus:
    """Fan-out for :class:`LiveEvent` subscribers, grouped by channel."""

    def __init__(self, *, max_queue_size: int = _MAX_QUEUE_SIZE) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: dict[str, set[asyncio.Queue[LiveEvent]]] = defaultdict(set)

    def subscribe(self, channel: str) -> asyncio.Queue[LiveEvent]:
        """Register a queue for ``channel``; pass it to :meth:`unsubscribe` when done."""
        queue: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers[channel].add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue[LiveEvent]) -> None:
        """Stop delivering events to ``queue``."""
        queues = self._subscribers.get(channel)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._subscribers.pop(channel, None)

    def publish(self, event: LiveEvent) -> None:
        """Deliver ``event`` to every subscriber of its channel."""
        for queue in tuple(self._subscribers.get(event.channel, ())):
            if queue.full():
                # Drop the oldest event; a consumer may have just drained it.
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)


live_event_bus = LiveEventBus()


def publish_task_event(event_type: EventType, task_ids: Iterable[str]) -> None:
    """Publish a Task mutation on the ``resources/tasks`` channel, de-duplicating ids."""
    ids = tuple(dict.fromkeys(task_ids))
    if not ids:
        return
    live_event_bus.publish(
        LiveEvent(channel=TASKS_CHANNEL, type=event_type, ids=ids, date=utcnow())
    )


def encode_live_event(event: LiveEvent) -> bytes:
    """Encode ``event`` as a named ``live`` Server-Sent Event."""
    data = {
        "channel": event.channel,
        "type": event.type,
        "payload": {"ids": list(event.ids)},
        "date": event.date.isoformat(),
    }
    return f"event: live\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()
