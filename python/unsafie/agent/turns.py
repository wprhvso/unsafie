import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.update import UpdateRepository

logger = logging.getLogger(__name__)

ChatKey = tuple[int, int]

chat_locks: dict[ChatKey, asyncio.Lock] = defaultdict(asyncio.Lock)
running: set[UUID] = set()


@dataclass(frozen=True)
class Plan:
    turn: Turn
    resume: str | None
    fork: bool
    session_id: str | None
    inject: bool
    in_context: bool


async def route(
    *,
    bot_id: int,
    chat_id: int,
    user_id: int,
    reply_to: int | None,
    update_db_id: int | None,
) -> Plan:
    prefix = f"bot={bot_id} chat={chat_id}"
    async with chat_locks[(bot_id, chat_id)]:
        async with SessionLocal() as session:
            turns = TurnRepository(session)
            updates = UpdateRepository(session)
            owner = await turns.owner(bot_id, chat_id, reply_to) if reply_to is not None else None

            if owner is not None and owner.id in running:
                if update_db_id is not None:
                    await updates.attach(update_db_id, owner.id)
                logger.info(
                    "%s reply_to=%s -> inject into running turn=%s", prefix, reply_to, owner.id
                )
                return Plan(owner, None, False, None, inject=True, in_context=True)

            if owner is None or owner.session_id is None:
                session_id = str(uuid.uuid4())
                resume, fork = None, False
                why = "new session"
            elif await turns.is_session_head(owner):
                session_id, resume, fork = owner.session_id, owner.session_id, False
                why = "continue"
            else:
                session_id, resume, fork = None, owner.session_id, True
                why = "fork"

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
            running.add(turn.id)
            logger.info(
                "%s reply_to=%s owner=%s -> turn=%s (%s) resume=%s",
                prefix,
                reply_to,
                owner.id if owner else None,
                turn.id,
                why,
                resume,
            )
            return Plan(turn, resume, fork, session_id, inject=False, in_context=owner is not None)


async def finish_or_continue(turn_id: UUID, bot_id: int, chat_id: int, drain) -> str | None:
    async with chat_locks[(bot_id, chat_id)]:
        leftover = drain(turn_id)
        if leftover is None:
            running.discard(turn_id)
        return leftover


def abandon(turn_id: UUID) -> None:
    running.discard(turn_id)
