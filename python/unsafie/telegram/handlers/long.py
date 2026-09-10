import contextlib

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from unsafie.agent.runtime import handle
from unsafie.database import SessionLocal
from unsafie.database.repositories.chat import ChatRepository
from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.long_input import (
    LongCallback,
    LongChoice,
    LongTarget,
    long_input_service,
)


def _without_command(message: Message) -> Message:
    text = (message.text or message.caption or "").strip()
    parts = text.split(maxsplit=1)
    cleaned = parts[1] if len(parts) > 1 else ""
    return message.model_copy(update={"text": cleaned}).as_(message.bot)


def is_collecting(message: Message, bot_id: int) -> bool:
    return long_input_service.collecting(bot_id, message.chat.id)


def build_long_router() -> Router:
    router = Router()

    @router.message(Command("long"))
    async def long_command(message: Message, bot_id: int) -> None:
        if not message.bot:
            return
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)
        cleaned = _without_command(message)
        initial = cleaned if cleaned.text else None
        await long_input_service.start(
            message.bot, bot_id, message.chat.id, initial, LongTarget.CHAT, locale,
        )

    @router.message(Command("system_long"))
    async def system_long_command(message: Message, bot_id: int) -> None:
        if not message.bot:
            return
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)
        cleaned = _without_command(message)
        initial = cleaned if cleaned.text else None
        await long_input_service.start(
            message.bot, bot_id, message.chat.id, initial, LongTarget.SYSTEM, locale,
        )

    @router.callback_query(LongCallback.filter())
    async def long_callback(query: CallbackQuery, callback_data: LongCallback, bot_id: int) -> None:
        if not query.message or not query.bot:
            await query.answer()
            return

        user_id = query.from_user.id
        chat_id = query.message.chat.id
        locale = await locale_for(user_id, query.from_user)

        if callback_data.choice == LongChoice.RESET.value:
            await long_input_service.close(bot_id, chat_id)
            await query.answer(t("cmd-long-reset-ok", locale))
            with contextlib.suppress(Exception):
                await query.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=query.message.message_id,
                    text=t("cmd-long-reset-ok", locale),
                    reply_markup=None,
                )
            return

        collected = await long_input_service.close(bot_id, chat_id)
        if not collected or not collected.messages:
            await query.answer(t("cmd-long-empty", locale), show_alert=True)
            return

        full_text = "\n\n".join(
            t_part for m in collected.messages if (t_part := (m.text or m.caption or "").strip())
        )
        if not full_text:
            await query.answer(t("cmd-long-empty", locale), show_alert=True)
            return

        if collected.target == LongTarget.SYSTEM:
            async with SessionLocal() as session:
                repo = ChatRepository(session)
                await repo.set_system(bot_id, chat_id, full_text)
            await query.answer(t("cmd-system-ok", locale))
            with contextlib.suppress(Exception):
                await query.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=query.message.message_id,
                    text=t("cmd-system-ok", locale),
                    reply_markup=None,
                )
            return

        await query.answer()
        with contextlib.suppress(Exception):
            await query.bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text="✅ " + t("cmd-long-send", locale),
                reply_markup=None,
            )

        first = collected.messages[0]
        combined = first.model_copy(update={"text": full_text}).as_(query.bot)
        await handle(combined, bot_id, update_db_id=None)

    @router.message(is_collecting)
    async def collected_message(message: Message, bot_id: int) -> None:
        if not message.bot:
            return
        await long_input_service.append(message.bot, bot_id, message.chat.id, message)

    return router
