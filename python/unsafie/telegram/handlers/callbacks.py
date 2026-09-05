import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from unsafie.agent.runtime import handle_callback

logger = logging.getLogger(__name__)


def build_callbacks_router() -> Router:
    router = Router()

    @router.callback_query()
    async def callback_handler(query: CallbackQuery, bot_id: int, update_db_id: int | None) -> None:
        message = query.message if isinstance(query.message, Message) else None
        logger.info(
            "bot=%s chat=%s callback=%s from=%s data=%r msg=%s",
            bot_id,
            message.chat.id if message else None,
            query.id,
            query.from_user.id,
            query.data,
            message.message_id if message else None,
        )
        try:
            await query.answer()
        except TelegramAPIError as e:
            logger.warning("bot=%s callback=%s answer failed: %s", bot_id, query.id, e)
        if message is None or query.data is None:
            return
        await handle_callback(query, message, bot_id, update_db_id)

    return router
