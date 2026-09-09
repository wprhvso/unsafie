import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from unsafie import cluster
from unsafie.agent import cancel, queue
from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn, TurnStatus
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Plan:
    turn: Turn
    inject: bool
    in_context: bool


def chat_lock(bot_id: int, chat_id: int) -> str:
    return f"chat:{bot_id}:{chat_id}"


def accepting(turn: Turn) -> bool:
    if turn.status != TurnStatus.RUNNING or turn.heartbeat_at is None:
        return False
    age = (datetime.now(UTC) - turn.heartbeat_at).total_seconds()
    return age < settings.turn_stale_after


async def seal(turn_id: UUID) -> None:
    async with SessionLocal() as session:
        await TurnRepository(session).seal(turn_id)


async def route(
    *,
    bot_id: int,
    chat_id: int,
    user_id: int,
    reply_to: int | None,
    update_db_id: int | None,
    is_inline: bool = False,
    inline_message_id: str | None = None,
    turn_reply_to: int | None = None,
) -> Plan:
    prefix = f"bot={bot_id} chat={chat_id}"
    async with cluster.lock(
        chat_lock(bot_id, chat_id),
        ttl=settings.chat_lock_ttl,
        wait=settings.chat_lock_wait,
        renew=True,
    ):
        async with SessionLocal() as session:
            turns = TurnRepository(session)
            updates = UpdateRepository(session)
            owner = await turns.owner(bot_id, chat_id, reply_to) if reply_to is not None else None

            if owner is not None and accepting(owner):
                if update_db_id is not None:
                    await updates.attach(update_db_id, owner.id)
                logger.info(
                    "%s reply_to=%s -> inject into turn=%s running on %s",
                    prefix,
                    reply_to,
                    owner.id,
                    owner.instance_id,
                )
                return Plan(owner, inject=True, in_context=True)

            turn = await turns.create(
                bot_id=bot_id,
                chat_id=chat_id,
                user_id=user_id,
                parent=owner,
                reply_to=turn_reply_to if turn_reply_to is not None else reply_to,
                is_inline=is_inline,
                inline_message_id=inline_message_id,
            )
            if update_db_id is not None:
                await updates.attach(update_db_id, turn.id)
            logger.info(
                "%s reply_to=%s owner=%s -> turn=%s root=%s",
                prefix,
                reply_to,
                owner.id if owner else None,
                turn.id,
                turn.root_id,
            )
            return Plan(turn, inject=False, in_context=owner is not None)


async def finish_or_continue(turn_id: UUID, bot_id: int, chat_id: int) -> str | None:
    async with cluster.lock(
        chat_lock(bot_id, chat_id), ttl=settings.chat_lock_ttl, wait=settings.chat_lock_wait
    ):
        leftover, _ = await queue.drain(turn_id)
        if leftover is None:
            await seal(turn_id)
        return leftover


_last_progress: dict[UUID, float] = {}


def touch(turn_id: UUID) -> None:
    _last_progress[turn_id] = time.monotonic()


async def _beat(turn_id: UUID, owner: asyncio.Task) -> None:
    while True:
        await asyncio.sleep(settings.turn_heartbeat)
        try:
            last = _last_progress.get(turn_id, time.monotonic())
            stall_limit = settings.agent_block_timeout + settings.turn_stale_after
            if time.monotonic() - last > stall_limit:
                logger.warning(
                    "turn=%s stalled for %.0fs with no progress, cancelling",
                    turn_id,
                    time.monotonic() - last,
                )
                owner.cancel()
                return
            async with SessionLocal() as session:
                await TurnRepository(session).beat(turn_id)
            if await cancel.asked(turn_id):
                logger.info("turn=%s was asked to stop, cancelling it here", turn_id)
                owner.cancel()
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("turn=%s heartbeat failed", turn_id, exc_info=True)


_here: dict[UUID, asyncio.Task] = {}
_idle = asyncio.Event()
_idle.set()


def busy() -> list[UUID]:
    return sorted(_here)


async def stop(turn_id: UUID) -> None:
    """Stop a turn: instantly if it runs here, through redis if it runs elsewhere."""
    await queue.clear(turn_id)
    task = _here.get(turn_id)
    if task is not None:
        logger.info("turn=%s stopped on this instance", turn_id)
        task.cancel()
        return
    await cancel.ask(turn_id)


async def drain(grace: float) -> list[UUID]:
    if not _here:
        return []
    logger.info("waiting up to %ss for turn(s) %s to finish", grace, busy())
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_idle.wait(), timeout=grace)
    return busy()


@contextlib.asynccontextmanager
async def alive(turn_id: UUID) -> AsyncIterator[None]:
    owner = asyncio.current_task()
    assert owner is not None
    _here[turn_id] = owner
    touch(turn_id)
    _idle.clear()
    await cancel.clear(turn_id)
    task = asyncio.create_task(_beat(turn_id, owner), name=f"heartbeat:{turn_id}")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        _here.pop(turn_id, None)
        _last_progress.pop(turn_id, None)
        if not _here:
            _idle.set()
