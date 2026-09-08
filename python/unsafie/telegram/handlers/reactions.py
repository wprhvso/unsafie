import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import MessageReactionUpdated

from unsafie import artifacts
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.repositories.turn import TurnRepository
from unsafie.telegram import sender

logger = logging.getLogger(__name__)


def build_reactions_router() -> Router:
    router = Router()

    @router.message_reaction()
    async def reaction_handler(event: MessageReactionUpdated, bot_id: int) -> None:
        if not event.new_reaction or event.bot is None:
            return
        chat_id = event.chat.id
        async with SessionLocal() as session:
            turn = await TurnRepository(session).owner(bot_id, chat_id, event.message_id)
        if turn is None:
            return
        slug = await artifacts.of_turn(turn.id)
        if slug is None:
            logger.info("bot=%s chat=%s turn=%s has no live artifact", bot_id, chat_id, turn.id)
            return
        try:
            await sender.send(
                event.bot,
                bot_id=bot_id,
                chat_id=chat_id,
                markdown=artifacts.url(slug),
                kind=ResponseKind.SYSTEM,
                reply_to=event.message_id,
                silent=True,
                preview=False,
            )
        except TelegramAPIError as e:
            logger.warning("bot=%s chat=%s turn link not delivered: %s", bot_id, chat_id, e)

    return router
