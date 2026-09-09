import asyncio
import logging
from uuid import UUID

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.models.turn import TurnStatus
from unsafie.database.repositories.turn import TurnRepository

logger = logging.getLogger(__name__)

_tasks: dict[UUID, asyncio.Task] = {}
_events: dict[UUID, asyncio.Event] = {}


def register_subagent_task(turn_id: UUID, task: asyncio.Task) -> None:
    _tasks[turn_id] = task
    _events[turn_id] = asyncio.Event()
    task.add_done_callback(lambda _: _tasks.pop(turn_id, None))


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
    deadline = asyncio.get_running_loop().time() + timeout
    for tid in turn_ids:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        async with SessionLocal() as session:
            t = await TurnRepository(session).get(tid)
            if t and t.status in (TurnStatus.DONE, TurnStatus.FAILED, TurnStatus.CANCELLED):
                continue
        ev = _events.setdefault(tid, asyncio.Event())
        try:
            await asyncio.wait_for(ev.wait(), timeout=remaining)
        except TimeoutError:
            break
        except Exception:
            pass


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
