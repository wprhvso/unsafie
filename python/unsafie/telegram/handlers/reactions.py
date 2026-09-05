import logging

from aiogram import Router
from aiogram.types import MessageReactionUpdated

from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.repositories.response import ResponseRepository
from unsafie.database.repositories.share import ShareRepository
from unsafie.settings import settings
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
            response = await ResponseRepository(session).by_message(
                bot_id, chat_id, event.message_id
            )
            if response is None or response.kind != ResponseKind.AGENT:
                return
            slug = await ShareRepository(session).get_or_create(response.id)
        if slug is None:
            logger.error("bot=%s chat=%s share slug not allocated", bot_id, chat_id)
            return
        first = response.message_ids[0] if response.message_ids else event.message_id
        await sender.send(
            event.bot,
            bot_id=bot_id,
            chat_id=chat_id,
            markdown=f"{settings.share_origin}/{slug}",
            kind=ResponseKind.SYSTEM,
            reply_to=first,
        )

    return router
