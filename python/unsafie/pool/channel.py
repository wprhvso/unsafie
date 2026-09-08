import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.models.pool import CommandStatus, PoolCommand
from unsafie.pool import keys, registry
from unsafie.settings import settings
from unsafie_wire import channel as wire

logger = logging.getLogger(__name__)

CHUNK_WAIT = 5.0
# A blocking pop must come back before the socket timeout of the shared client does,
# otherwise redis-py raises a TimeoutError instead of handing over an empty answer.
BLOCK = max(1, int(min(CHUNK_WAIT, settings.redis_timeout - 1)))


@dataclass
class Result:
    command_id: str
    machine: str
    exit_code: int | None = None
    output: str = ""
    seconds: float = 0.0
    truncated: bool = False
    frames: list[dict] = field(default_factory=list)

    @property
    def timed_out(self) -> bool:
        return self.exit_code is None


async def send(
    machine: str,
    command: str,
    *,
    user_id: int | None,
    turn_id: UUID | None = None,
    cwd: str | None = None,
    timeout: float | None = None,
    stdin: str | None = None,
    background: bool = False,
) -> str:
    command_id = uuid.uuid4().hex
    frame = wire.command(
        command_id,
        command,
        cwd=cwd,
        timeout=timeout,
        stdin=stdin,
        background=background,
    )
    redis = cluster.client()
    await redis.rpush(keys.inbox(machine), wire.encode(frame))
    await redis.expire(keys.inbox(machine), int(settings.pool_output_ttl))
    async with SessionLocal() as session:
        session.add(
            PoolCommand(
                id=uuid.UUID(command_id),
                machine=machine,
                user_id=user_id,
                turn_id=turn_id,
                command=command[:8000],
                background=background,
            )
        )
        await session.commit()
    logger.info("pool %s <- %s (%s)", machine, command_id, command[:120])
    return command_id


async def pull(machine: str, wait: float) -> list[dict]:
    redis = cluster.client()
    deadline = time.monotonic() + max(wait, 0.0)
    frames: list[dict] = []
    while True:
        raw = await redis.lpop(keys.inbox(machine), 32)
        if raw:
            for line in raw if isinstance(raw, list) else [raw]:
                decoded = wire.decode(line)
                if decoded is not None:
                    frames.append({"kind": str(decoded.kind), "id": decoded.id, **decoded.body})
            return frames
        if time.monotonic() >= deadline:
            return frames
        await asyncio.sleep(0.25)


async def push(command_id: str, frames: list[dict]) -> None:
    redis = cluster.client()
    payload = [json.dumps(frame, ensure_ascii=False) for frame in frames]
    if payload:
        await redis.rpush(keys.outbox(command_id), *payload)
        await redis.expire(keys.outbox(command_id), int(settings.pool_output_ttl))


async def collect(
    command_id: str, machine: str, timeout: float, limit: int | None = None
) -> Result:
    redis = cluster.client()
    cap = limit or settings.pool_max_output
    result = Result(command_id, machine)
    started = time.monotonic()
    pieces: list[str] = []
    size = 0
    while time.monotonic() - started < timeout:
        popped = await redis.blpop([keys.outbox(command_id)], timeout=BLOCK)
        if popped is None:
            if not await registry.alive(machine):
                result.output = "".join(pieces)
                result.seconds = time.monotonic() - started
                await _finish(command_id, None, size, CommandStatus.LOST)
                return result
            continue
        frame = json.loads(popped[1])
        kind = frame.get("kind")
        if kind == str(wire.FrameKind.OUTPUT):
            data = str(frame.get("data") or "")
            size += len(data)
            if size <= cap:
                pieces.append(data)
            else:
                result.truncated = True
            continue
        result.frames.append(frame)
        if kind == str(wire.FrameKind.EXIT):
            result.exit_code = int(frame.get("code") or 0)
            result.seconds = float(frame.get("seconds") or (time.monotonic() - started))
            result.output = "".join(pieces)
            await _finish(command_id, result.exit_code, size, CommandStatus.DONE)
            return result
    result.output = "".join(pieces)
    result.seconds = time.monotonic() - started
    await _finish(command_id, None, size, CommandStatus.FAILED)
    return result


async def _finish(command_id: str, code: int | None, size: int, status: CommandStatus) -> None:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(PoolCommand).where(PoolCommand.id == uuid.UUID(command_id))
        )
        if row is None:
            return
        row.status = status
        row.exit_code = code
        row.bytes = size
        row.finished_at = datetime.now(UTC)
        await session.commit()


async def started(command_id: str) -> None:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(PoolCommand).where(PoolCommand.id == uuid.UUID(command_id))
        )
        if row is None:
            return
        row.status = CommandStatus.RUNNING
        row.started_at = datetime.now(UTC)
        await session.commit()


async def run(
    machine: str,
    command: str,
    *,
    user_id: int | None,
    turn_id: UUID | None = None,
    cwd: str | None = None,
    timeout: float | None = None,
    stdin: str | None = None,
) -> Result:
    limit = min(timeout or settings.pool_command_timeout, settings.pool_max_command_timeout)
    command_id = await send(
        machine,
        command,
        user_id=user_id,
        turn_id=turn_id,
        cwd=cwd,
        timeout=limit,
        stdin=stdin,
    )
    return await collect(command_id, machine, limit + CHUNK_WAIT * 2)


async def cancel(command_id: str, machine: str) -> None:
    await tell(machine, wire.cancel(command_id))
    async with SessionLocal() as session:
        row = await session.scalar(
            select(PoolCommand).where(PoolCommand.id == uuid.UUID(command_id))
        )
        if row is None:
            return
        row.status = CommandStatus.CANCELLED
        row.finished_at = datetime.now(UTC)
        await session.commit()


async def tell(machine: str, frame: wire.Frame) -> None:
    redis = cluster.client()
    await redis.rpush(keys.inbox(machine), wire.encode(frame))
    await redis.expire(keys.inbox(machine), int(settings.pool_output_ttl))
