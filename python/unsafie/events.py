import asyncio
import fnmatch
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from unsafie.settings import settings

logger = logging.getLogger(__name__)

GAP = "gap"


@dataclass(frozen=True)
class Event:
    id: int
    kind: str
    at: datetime
    data: dict[str, Any] = field(default_factory=dict)

    def matches(self, kinds: list[str] | None, match: dict[str, Any] | None) -> bool:
        if kinds and not any(fnmatch.fnmatchcase(self.kind, k) for k in kinds):
            return False
        if match and any(self.data.get(k) != v for k, v in match.items()):
            return False
        return True


class Bus:
    def __init__(self, buffer: int, queue: int) -> None:
        self._buffer: deque[Event] = deque(maxlen=buffer)
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._queue_size = queue
        self._next_id = 1

    def publish(self, kind: str, /, **data: Any) -> Event:
        event = Event(self._next_id, kind, datetime.now(UTC), data)
        self._next_id += 1
        self._buffer.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("events: subscriber queue full, dropping %s#%s", kind, event.id)
        return event

    def oldest_id(self) -> int | None:
        return self._buffer[0].id if self._buffer else None

    def latest_id(self) -> int:
        return self._next_id - 1

    def replay(self, after_id: int | None) -> tuple[list[Event], bool]:
        if after_id is None:
            return list(self._buffer), False
        oldest = self.oldest_id()
        gap = oldest is not None and after_id < oldest - 1
        return [e for e in self._buffer if e.id > after_id], gap

    async def subscribe(
        self,
        kinds: list[str] | None = None,
        match: dict[str, Any] | None = None,
        after_id: int | None = None,
    ) -> AsyncIterator[Event | str]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        backlog, gap = self.replay(after_id)
        self._subscribers.add(q)
        try:
            if gap:
                yield GAP
            for e in backlog:
                if e.matches(kinds, match):
                    yield e
            while True:
                e = await q.get()
                if e.matches(kinds, match):
                    yield e
        finally:
            self._subscribers.discard(q)

    def recent(
        self, kinds: list[str] | None = None, match: dict[str, Any] | None = None, limit: int = 100
    ) -> list[Event]:
        out = [e for e in reversed(self._buffer) if e.matches(kinds, match)]
        return out[:limit]


bus = Bus(settings.events_buffer, settings.events_queue)
publish = bus.publish
subscribe = bus.subscribe
