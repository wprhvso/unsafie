import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeout

from unsafie import artifacts, cluster
from unsafie.database.models.turn import Turn
from unsafie.settings import settings

logger = logging.getLogger(__name__)

BODY = "b"
STREAM = "live"
GAP = "gap"
TRUNCATED = "live.truncated"


def stream_key(turn_id: UUID | str) -> str:
    return cluster.key(STREAM, str(turn_id))


def token_key(token: str) -> str:
    return cluster.key(STREAM, "token", token)


def link_key(turn_id: UUID | str) -> str:
    return cluster.key(STREAM, "link", str(turn_id))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def clip(value: str, limit: int | None = None) -> tuple[str, int]:
    limit = settings.live_max_text if limit is None else limit
    if len(value) <= limit:
        return value, 0
    return value[:limit], len(value) - limit


@dataclass
class Frame:
    kind: str
    at: str
    data: dict[str, Any] = field(default_factory=dict)


class Live:
    def __init__(self, turn_id: UUID, token: str) -> None:
        self.turn_id = turn_id
        self.token = token
        self.key = stream_key(turn_id)
        self.frames = 0
        self.bytes = 0
        self._buffer: list[Frame] = []
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._full = False

    def emit(self, kind: str, /, **data: Any) -> None:
        self._push(Frame(kind, _now(), data))

    def append(self, kind: str, step: int, index: int, text: str) -> None:
        if not text or self._full:
            return
        last = self._buffer[-1] if self._buffer else None
        if (
            last is not None
            and last.kind == kind
            and last.data.get("step") == step
            and last.data.get("index") == index
            and len(last.data["text"]) + len(text) <= settings.live_max_text
        ):
            last.data["text"] += text
            return
        body, cut = clip(text)
        frame = Frame(kind, _now(), {"step": step, "index": index, "text": body})
        if cut:
            frame.data["cut"] = cut
        self._push(frame)

    def _push(self, frame: Frame) -> None:
        if self._full and frame.kind != "turn.end":
            return
        if len(self._buffer) >= settings.live_queue:
            logger.warning("live: turn=%s buffer is full, %s dropped", self.turn_id, frame.kind)
            return
        self._buffer.append(frame)
        self._wake.set()

    def _encode(self, frame: Frame) -> str:
        self.frames += 1
        body = json.dumps(
            {"seq": self.frames, "kind": frame.kind, "at": frame.at, "data": frame.data},
            ensure_ascii=False,
            default=str,
        )
        self.bytes += len(body)
        return body

    def _batch(self) -> list[str]:
        out: list[str] = []
        while self._buffer and len(out) < settings.live_batch:
            out.append(self._encode(self._buffer.pop(0)))
            if self.bytes >= settings.live_max_bytes and not self._full:
                self._full = True
                self._buffer = [f for f in self._buffer if f.kind == "turn.end"]
                out.append(self._encode(Frame("note", _now(), {"name": TRUNCATED})))
                logger.warning(
                    "live: turn=%s wrote %s bytes, stopping there", self.turn_id, self.bytes,
                )
                break
        return out

    async def flush(self) -> None:
        while self._buffer:
            batch = self._batch()
            if not batch:
                return
            try:
                pipe = cluster.client().pipeline(transaction=False)
                for body in batch:
                    pipe.xadd(
                        self.key, {BODY: body}, maxlen=settings.live_buffer, approximate=True,
                    )
                pipe.pexpire(self.key, int(settings.live_ttl * 1000))
                await pipe.execute()
            except (cluster.Unavailable, RedisError, OSError):
                logger.warning(
                    "live: turn=%s lost %s frame(s)", self.turn_id, len(batch), exc_info=True,
                )

    async def _pump(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            await asyncio.sleep(settings.live_flush)
            await self.flush()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._pump(), name=f"live:{self.turn_id}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.flush()


_streams: dict[UUID, Live] = {}


async def _allocate(turn: Turn) -> str | None:
    token = await artifacts.for_turn(turn)
    if token is None:
        return None
    client = cluster.client()
    ttl = int(settings.live_ttl * 1000)
    await client.set(token_key(token), str(turn.id), px=ttl)
    await client.set(link_key(turn.id), token, px=ttl)
    return token


async def begin(turn: Turn) -> Live | None:
    if not settings.live_enabled:
        return None
    try:
        token = await _allocate(turn)
    except (cluster.Unavailable, RedisError, OSError):
        logger.warning("live: turn=%s got no token", turn.id, exc_info=True)
        return None
    if token is None:
        logger.error("live: turn=%s got no artifact slug", turn.id)
        return None
    stream = Live(turn.id, token)
    stream.start()
    _streams[turn.id] = stream
    logger.info("live: turn=%s streams to %s", turn.id, artifacts.url(token))
    return stream


async def end(turn_id: UUID) -> None:
    stream = _streams.pop(turn_id, None)
    if stream is None:
        return
    await stream.stop()
    logger.info("live: turn=%s wrote %s frame(s), %s bytes", turn_id, stream.frames, stream.bytes)


async def seal(turn_id: UUID, **data: Any) -> None:
    if turn_id in _streams:
        return
    body = json.dumps(
        {"seq": 0, "kind": "turn.end", "at": _now(), "data": data},
        ensure_ascii=False,
        default=str,
    )
    try:
        client = cluster.client()
        if not await client.exists(stream_key(turn_id)):
            return
        await client.xadd(
            stream_key(turn_id), {BODY: body}, maxlen=settings.live_buffer, approximate=True,
        )
        await client.pexpire(stream_key(turn_id), int(settings.live_ttl * 1000))
    except (cluster.Unavailable, RedisError, OSError):
        logger.warning("live: turn=%s could not be sealed", turn_id, exc_info=True)


def of(turn_id: UUID | None) -> Live | None:
    return _streams.get(turn_id) if turn_id is not None else None


def emit(turn_id: UUID | None, kind: str, /, **data: Any) -> None:
    stream = of(turn_id)
    if stream is not None:
        stream.emit(kind, **data)


async def turn_of(token: str) -> UUID | None:
    raw = await cluster.client().get(token_key(token))
    if not raw:
        return None
    try:
        raw_str = raw.decode() if isinstance(raw, bytes) else str(raw)
        return UUID(raw_str)
    except ValueError:
        return None


async def token_of(turn_id: UUID) -> str | None:
    raw = await cluster.client().get(link_key(turn_id))
    return raw.decode() if isinstance(raw, bytes) else raw


def _decode(entry_id: str, fields: dict | None) -> dict | None:
    if fields is None:
        return None
    try:
        frame = json.loads(fields[BODY])
    except (KeyError, ValueError, TypeError):
        logger.warning("live: entry %s is unreadable", entry_id)
        return None
    frame["id"] = entry_id
    return frame


async def bounds(turn_id: UUID) -> tuple[str | None, str | None]:
    client = cluster.client()
    first = await client.xrange(stream_key(turn_id), count=1)
    last = await client.xrevrange(stream_key(turn_id), count=1)
    f_id = first[0][0] if first else None
    l_id = last[0][0] if last else None
    return (f_id.decode() if isinstance(f_id, bytes) else f_id, l_id.decode() if isinstance(l_id, bytes) else l_id)


async def history(turn_id: UUID, after: str | None = None, limit: int | None = None) -> list[dict]:
    raw_entries = await cluster.client().xrange(
        stream_key(turn_id), min=after or "-", count=limit or settings.live_buffer,
    )
    out: list[dict] = []
    if not raw_entries:
        return out
    for item in raw_entries:
        entry_raw, fields = item[0], item[1]
        entry_id = entry_raw.decode() if isinstance(entry_raw, bytes) else str(entry_raw)
        if entry_id == after:
            continue
        frame = _decode(entry_id, fields if isinstance(fields, dict) else None)
        if frame is not None:
            out.append(frame)
    return out


async def follow(turn_id: UUID, after: str | None = None) -> AsyncIterator[dict | str]:
    client = cluster.reader()
    key = stream_key(turn_id)
    if after is not None:
        oldest, _ = await bounds(turn_id)
        if oldest is not None and _position(after) < _position(oldest):
            yield GAP
    cursor = after or "0-0"
    while True:
        try:
            entries = await client.xread(
                {key: cursor},
                count=settings.live_batch,
                block=int(settings.live_block * 1000),
            )
        except RedisTimeout:
            logger.debug("live: turn=%s quiet read window", turn_id)
            continue
        for stream_pair in entries or []:
            if not isinstance(stream_pair, tuple | list) or len(stream_pair) < 2:
                continue
            for entry_raw, fields in stream_pair[1]:
                entry_id = entry_raw.decode() if isinstance(entry_raw, bytes) else str(entry_raw)
                cursor = entry_id
                frame = _decode(entry_id, fields)
                if frame is not None:
                    yield frame


def _position(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    try:
        return int(ms), int(seq or 0)
    except ValueError:
        return 0, 0
