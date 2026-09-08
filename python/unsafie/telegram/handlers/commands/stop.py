import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from unsafie.agent import turns
from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository
from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


async def _targets(bot_id: int, chat_id: int, reply_to: int | None) -> list[Turn]:
    """Everything running in the chat, or only what the replied-to message started."""
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        running = await repo.running(bot_id, chat_id)
        if reply_to is None:
            return running
        owner = await repo.owner(bot_id, chat_id, reply_to)
        if owner is None:
            return []
        family = await repo.lineage(owner.id)
    return [turn for turn in running if turn.id in family]


def build_stop_router() -> Router:
    router = Router()

    @router.message(Command("stop", "cancel"))
    async def stop_handler(message: Message, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        reply = message.reply_to_message
        reply_to = reply.message_id if reply else None
        targets = await _targets(bot_id, message.chat.id, reply_to)
        if not targets:
            key = (
                "commands-stop-nothing-here" if reply_to is not None else "commands-stop-nothing"
            )
            await answer(message, bot_id, t(key, locale))
            return
        for turn in targets:
            logger.info(
                "bot=%s chat=%s user=%s stops turn=%s", bot_id, message.chat.id, user_id, turn.id
            )
            await turns.stop(turn.id)
        key = "commands-stop-one" if len(targets) == 1 else "commands-stop-many"
        await answer(message, bot_id, t(key, locale, n=len(targets)))

    return router
