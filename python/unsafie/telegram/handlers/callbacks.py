import contextlib
import logging
from uuid import UUID

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from unsafie.agent.runtime import handle_callback
from unsafie.database import SessionLocal
from unsafie.database.models.turn import TurnStatus
from unsafie.database.repositories.turn import TurnRepository
from unsafie.fluent import t
from unsafie.telegram.group import is_admin
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.retry import RetryCallback, retry_markup

logger = logging.getLogger(__name__)


def build_callbacks_router() -> Router:
    router = Router()

    @router.callback_query(RetryCallback.filter())
    async def retry_callback_handler(
        query: CallbackQuery, callback_data: RetryCallback, bot_id: int,
    ) -> None:
        message = query.message if isinstance(query.message, Message) else None
        if message is None or query.bot is None:
            await query.answer()
            return

        user_id = query.from_user.id
        chat_id = message.chat.id
        locale = await locale_for(user_id, query.from_user)

        try:
            turn_uuid = UUID(callback_data.turn_id)
        except ValueError:
            await query.answer(t("commands-retry-not-found", locale), show_alert=True)
            return

        async with SessionLocal() as session:
            repo = TurnRepository(session)
            origin_turn = await repo.get(turn_uuid)

        if origin_turn is None:
            await query.answer(t("commands-retry-not-found", locale), show_alert=True)
            return

        if (
            message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
            and origin_turn.user_id != user_id
        ) and not await is_admin(query.bot, chat_id, user_id):
            await query.answer(t("commands-retry-denied", locale), show_alert=True)
            return

        if origin_turn.status == TurnStatus.RUNNING:
            await query.answer(t("commands-retry-already-running", locale), show_alert=True)
            return

        await query.answer(t("commands-retry-toast", locale))

        with contextlib.suppress(Exception):
            await query.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message.message_id,
                reply_markup=retry_markup(str(origin_turn.id), locale, in_progress=True),
            )

        from unsafie.agent.runtime import retry_turn

        await retry_turn(query.bot, origin_turn, locale)

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
        if query.data is None:
            return
        if message is None and query.inline_message_id is None:
            return
        await handle_callback(query, message, bot_id, update_db_id)

    return router
