import asyncio
import contextlib
from unsafie.log import get_logger
from uuid import UUID

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.models.turn import TurnStatus
from unsafie.database.repositories.turn import TurnRepository

logger = get_logger(__name__)

_tasks: dict[UUID, asyncio.Task] = {}
_events: dict[UUID, asyncio.Event] = {}


def _cleanup_subagent(turn_id: UUID) -> None:
    _tasks.pop(turn_id, None)


def register_subagent_task(turn_id: UUID, task: asyncio.Task) -> None:
    _tasks[turn_id] = task
    _events[turn_id] = asyncio.Event()
    task.add_done_callback(lambda _: _cleanup_subagent(turn_id))


def mark_subagent_done(turn_id: UUID) -> None:
    ev = _events.get(turn_id)
    if ev:
        ev.set()


async def notify_subagent_done(turn_id: UUID) -> None:
    mark_subagent_done(turn_id)
    try:
        redis = cluster.client()
        await redis.publish(f"subagent:{turn_id}", "done")
    except Exception:
        pass


async def wait_subagents(turn_ids: list[UUID], timeout: float = 600.0) -> None:
    if not turn_ids:
        return
    for tid in turn_ids:
        _events.setdefault(tid, asyncio.Event())

    pubsub = None
    listener_task = None
    try:
        redis = cluster.client()
        pubsub = redis.pubsub(ignore_subscribe_messages=True)
        channels = [f"subagent:{tid}" for tid in turn_ids]
        await pubsub.subscribe(*channels)

        async def _redis_listener() -> None:
            try:
                async for msg in pubsub.listen():
                    if msg.get("type") == "message":
                        ch = msg.get("channel", "")
                        if isinstance(ch, bytes):
                            ch = ch.decode("utf-8")
                        for tid in turn_ids:
                            if ch == f"subagent:{tid}":
                                mark_subagent_done(tid)
            except Exception:
                pass

        listener_task = asyncio.create_task(_redis_listener(), name="subagents:redis-listener")
    except Exception:
        pass

    deadline = asyncio.get_running_loop().time() + timeout
    try:
        for tid in turn_ids:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            ev = _events.get(tid) or asyncio.Event()
            while not ev.is_set():
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                async with SessionLocal() as session:
                    t = await TurnRepository(session).get(tid)
                    if t and t.status in (TurnStatus.DONE, TurnStatus.FAILED, TurnStatus.CANCELLED):
                        ev.set()
                        break
                try:
                    await asyncio.wait_for(ev.wait(), timeout=min(3.0, max(0.5, remaining)))
                except TimeoutError:
                    pass
                except Exception:
                    break
    finally:
        if listener_task is not None:
            listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener_task
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe()
                closer = getattr(pubsub, "aclose", None) or pubsub.close
                await closer()
        for tid in turn_ids:
            _events.pop(tid, None)


async def cancel_subagents_of(parent_id: UUID) -> None:
    async with SessionLocal() as session:
        children = await TurnRepository(session).subagents(parent_id)
    for c in children:
        if c.status == TurnStatus.RUNNING:
            task = _tasks.get(c.id)
            if task and not task.done():
                task.cancel()
            from unsafie.agent import turns

            await turns.stop(c.id)
