from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from unsafie.database import SessionLocal
from unsafie.database.models.chat import GroupMode
from unsafie.database.repositories.chat import ChatRepository
from unsafie.fluent import t
from unsafie.telegram.group import is_admin
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer


class GroupModeCallback(CallbackData, prefix="grp_mode"):
    mode: str


def group_mode_keyboard(current_mode: str, locale: str) -> InlineKeyboardMarkup:
    options = [
        (GroupMode.MENTIONS, "commands-group-mode-mentions"),
        (GroupMode.ALL, "commands-group-mode-all"),
        (GroupMode.OFF, "commands-group-mode-off"),
    ]
    buttons = []
    for mode, label_key in options:
        marker = "🔘" if mode.value == current_mode else "⚪"
        label = f"{marker} {t(label_key, locale)}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label, callback_data=GroupModeCallback(mode=mode.value).pack()
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_group_router() -> Router:
    router = Router()

    @router.message(Command("group", "group_mode"))
    async def group_command(message: Message, bot_id: int) -> None:
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)

        if message.chat.type == ChatType.PRIVATE:
            await answer(message, bot_id, t("commands-group-private", locale))
            return

        if message.bot and not await is_admin(message.bot, message.chat.id, user_id):
            await answer(message, bot_id, t("commands-group-admin-only", locale))
            return

        async with SessionLocal() as session:
            chat_row = await ChatRepository(session).get(bot_id, message.chat.id)

        mode = (chat_row.group_mode if chat_row else None) or GroupMode.MENTIONS.value
        markup = group_mode_keyboard(mode, locale)
        await answer(message, bot_id, t("commands-group-menu", locale), reply_markup=markup)

    @router.callback_query(GroupModeCallback.filter())
    async def group_mode_callback(
        query: CallbackQuery, callback_data: GroupModeCallback, bot_id: int
    ) -> None:
        if not query.message or not query.bot:
            await query.answer()
            return

        user_id = query.from_user.id
        chat_id = query.message.chat.id
        locale = await locale_for(user_id, query.from_user)

        if not await is_admin(query.bot, chat_id, user_id):
            await query.answer(t("commands-group-admin-only", locale), show_alert=True)
            return

        new_mode = callback_data.mode
        async with SessionLocal() as session:
            repo = ChatRepository(session)
            await repo.set_group_mode(bot_id, chat_id, new_mode)

        mode_label = t(f"commands-group-mode-{new_mode}", locale)
        await query.answer(t("commands-group-mode-updated", locale, mode=mode_label))

        new_markup = group_mode_keyboard(new_mode, locale)
        try:
            await query.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=query.message.message_id,
                reply_markup=new_markup,
            )
        except Exception:
            pass

    return router
