import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from unsafie import cluster
from unsafie.agent import queue
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
                reply_to=reply_to,
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
        leftover = await queue.drain(turn_id)
        if leftover is None:
            await seal(turn_id)
        return leftover


async def _beat(turn_id: UUID) -> None:
    while True:
        await asyncio.sleep(settings.turn_heartbeat)
        try:
            async with SessionLocal() as session:
                await TurnRepository(session).beat(turn_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("turn=%s heartbeat failed", turn_id, exc_info=True)


_here: set[UUID] = set()
_idle = asyncio.Event()
_idle.set()


def busy() -> list[UUID]:
    return sorted(_here)


async def drain(grace: float) -> list[UUID]:
    if not _here:
        return []
    logger.info("waiting up to %ss for turn(s) %s to finish", grace, busy())
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_idle.wait(), timeout=grace)
    return busy()


@contextlib.asynccontextmanager
async def alive(turn_id: UUID) -> AsyncIterator[None]:
    _here.add(turn_id)
    _idle.clear()
    task = asyncio.create_task(_beat(turn_id), name=f"heartbeat:{turn_id}")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        _here.discard(turn_id)
        if not _here:
            _idle.set()
