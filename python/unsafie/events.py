import asyncio
import contextlib
import fnmatch
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import TimeoutError as RedisTimeout

from unsafie import cluster
from unsafie.settings import settings

logger = logging.getLogger(__name__)

GAP = "gap"
STREAM = "events"
BODY = "body"


@dataclass(frozen=True)
class Event:
    id: str
    kind: str
    at: datetime
    data: dict[str, Any] = field(default_factory=dict)

    def matches(self, kinds: list[str] | None, match: dict[str, Any] | None) -> bool:
        if kinds and not any(fnmatch.fnmatchcase(self.kind, k) for k in kinds):
            return False
        return not (match and any(self.data.get(k) != v for k, v in match.items()))


def position(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    try:
        return int(ms), int(seq or 0)
    except ValueError:
        return 0, 0


def _parse(entry_id: str, fields: dict) -> Event | None:
    try:
        body = json.loads(fields[BODY])
        return Event(entry_id, body["kind"], datetime.fromisoformat(body["at"]), body.get("data"))
    except (KeyError, ValueError, TypeError):
        logger.warning("events: entry %s is unreadable", entry_id)
        return None


class Bus:
    def __init__(self, maxlen: int, queue: int) -> None:
        self._maxlen = maxlen
        self._outbox: asyncio.Queue[str] = asyncio.Queue(maxsize=queue)
        self._writer: asyncio.Task | None = None
        self._dropped = 0

    @property
    def key(self) -> str:
        return cluster.key(STREAM)

    def publish(self, kind: str, /, **data: Any) -> None:
        payload = json.dumps(
            {"kind": kind, "at": datetime.now(UTC).isoformat(), "data": data},
            ensure_ascii=False,
            default=str,
        )
        try:
            self._outbox.put_nowait(payload)
        except asyncio.QueueFull:
            self._dropped += 1
            logger.warning("events: outbox full, dropped %s (%s total)", kind, self._dropped)

    def start(self) -> None:
        if self._writer is None:
            self._writer = asyncio.create_task(self._pump(), name="events-writer")
            logger.info("events -> %s (maxlen=%s)", self.key, self._maxlen)

    async def stop(self) -> None:
        if self._writer is None:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._outbox.join(), timeout=2.0)
        self._writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._writer
        self._writer = None

    async def _pump(self) -> None:
        while True:
            batch = [await self._outbox.get()]
            while len(batch) < settings.events_batch:
                try:
                    batch.append(self._outbox.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                pipe = cluster.client().pipeline(transaction=False)
                for payload in batch:
                    pipe.xadd(self.key, {BODY: payload}, maxlen=self._maxlen, approximate=True)
                await pipe.execute()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("events: %s entr(ies) not written", len(batch), exc_info=True)
            for _ in batch:
                self._outbox.task_done()

    async def bounds(self) -> tuple[str | None, str | None]:
        client = cluster.client()
        first = await client.xrange(self.key, count=1)
        last = await client.xrevrange(self.key, count=1)
        f_id = first[0][0] if first else None
        l_id = last[0][0] if last else None
        return (f_id.decode() if isinstance(f_id, bytes) else f_id, l_id.decode() if isinstance(l_id, bytes) else l_id)

    async def recent(
        self, kinds: list[str] | None = None, match: dict[str, Any] | None = None, limit: int = 100,
    ) -> list[Event]:
        entries = await cluster.client().xrevrange(self.key, count=self._maxlen)
        out: list[Event] = []
        if not entries:
            return out
        for item in entries:
            entry_raw, fields = item[0], item[1]
            entry_id = entry_raw.decode() if isinstance(entry_raw, bytes) else str(entry_raw)
            event = _parse(entry_id, fields if isinstance(fields, dict) else {})
            if event is not None and event.matches(kinds, match):
                out.append(event)
                if len(out) >= limit:
                    break
        return out

    async def subscribe(
        self,
        kinds: list[str] | None = None,
        match: dict[str, Any] | None = None,
        after_id: str | None = None,
    ) -> AsyncIterator[Event | str]:
        client = cluster.reader()
        oldest, _ = await self.bounds()
        if after_id is None:
            cursor = "0-0"
        else:
            if oldest is not None and position(after_id) < position(oldest):
                yield GAP
            cursor = after_id
        while True:
            try:
                entries = await client.xread(
                    {self.key: cursor},
                    count=settings.events_batch,
                    block=int(settings.events_block * 1000),
                )
            except RedisTimeout:
                logger.debug("events: quiet read window")
                continue
            for stream_pair in entries or []:
                if not isinstance(stream_pair, tuple | list) or len(stream_pair) < 2:
                    continue
                for entry_raw, fields in stream_pair[1]:
                    entry_id = entry_raw.decode() if isinstance(entry_raw, bytes) else str(entry_raw)
                    cursor = entry_id
                    event = _parse(entry_id, fields)
                    if event is not None and event.matches(kinds, match):
                        yield event


bus = Bus(settings.events_buffer, settings.events_queue)
publish = bus.publish
subscribe = bus.subscribe
