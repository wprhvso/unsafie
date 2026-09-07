import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from unsafie import cluster
from unsafie.agent import queue
from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Plan:
    turn: Turn
    resume: str | None
    fork: bool
    session_id: str | None
    inject: bool
    in_context: bool
    fork_at: int | None = None


def chat_lock(bot_id: int, chat_id: int) -> str:
    return f"chat:{bot_id}:{chat_id}"


def running_key(turn_id: UUID) -> str:
    return cluster.key("running", turn_id)


async def mark_running(turn_id: UUID) -> None:
    await cluster.client().set(
        running_key(turn_id), settings.instance_id, px=int(settings.turn_stale_after * 1000)
    )


async def is_running(turn_id: UUID) -> str | None:
    return await cluster.client().get(running_key(turn_id))


async def abandon(turn_id: UUID) -> None:
    await cluster.client().delete(running_key(turn_id))


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

            if owner is not None and (where := await is_running(owner.id)):
                if update_db_id is not None:
                    await updates.attach(update_db_id, owner.id)
                logger.info(
                    "%s reply_to=%s -> inject into turn=%s running on %s",
                    prefix,
                    reply_to,
                    owner.id,
                    where,
                )
                return Plan(owner, None, False, None, inject=True, in_context=True)

            fork_at = None
            if owner is None or owner.session_id is None:
                session_id = str(uuid.uuid4())
                resume, fork = None, False
                why = "new session"
            elif await turns.is_session_head(owner):
                session_id, resume, fork = owner.session_id, owner.session_id, False
                why = "continue"
            else:
                session_id, resume, fork = None, owner.session_id, True
                fork_at = owner.transcript_lines
                why = f"fork at line {fork_at}" if fork_at else "fork"

            turn = await turns.create(
                bot_id=bot_id,
                chat_id=chat_id,
                user_id=user_id,
                parent=owner,
                reply_to=reply_to,
                session_id=session_id,
                forked=fork,
            )
            if update_db_id is not None:
                await updates.attach(update_db_id, turn.id)
            await mark_running(turn.id)
            logger.info(
                "%s reply_to=%s owner=%s -> turn=%s (%s) resume=%s",
                prefix,
                reply_to,
                owner.id if owner else None,
                turn.id,
                why,
                resume,
            )
            return Plan(
                turn,
                resume,
                fork,
                session_id,
                inject=False,
                in_context=owner is not None,
                fork_at=fork_at,
            )


async def finish_or_continue(turn_id: UUID, bot_id: int, chat_id: int) -> str | None:
    async with cluster.lock(
        chat_lock(bot_id, chat_id), ttl=settings.chat_lock_ttl, wait=settings.chat_lock_wait
    ):
        leftover = await queue.drain(turn_id)
        if leftover is None:
            await abandon(turn_id)
        return leftover


async def _beat(turn_id: UUID) -> None:
    while True:
        await asyncio.sleep(settings.turn_heartbeat)
        try:
            await mark_running(turn_id)
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
