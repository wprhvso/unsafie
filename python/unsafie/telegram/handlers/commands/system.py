from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.database import SessionLocal
from unsafie.database.repositories.chat import ChatRepository
from unsafie.fluent import t
from unsafie.telegram.group import is_admin
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer


def build_system_router() -> Router:
    router = Router()

    @router.message(Command("system"))
    async def system_command(message: Message, command: CommandObject, bot_id: int) -> None:
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)
        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and message.bot and not await is_admin(message.bot, message.chat.id, user_id):
                await answer(message, bot_id, t("commands-group-admin-only", locale))
                return

        prompt = (command.args or "").strip()

        if not prompt:
            async with SessionLocal() as session:
                chat = await ChatRepository(session).get(bot_id, message.chat.id)
            if chat and chat.system:
                text = f"{t('cmd-system-ok', locale)}:\n\n<code>{chat.system}</code>\n\n{t('cmd-system-help', locale)}"
            else:
                text = t("cmd-system-help", locale)
            await answer(message, bot_id, text)
            return

        async with SessionLocal() as session:
            await ChatRepository(session).set_system(bot_id, message.chat.id, prompt)
        await answer(message, bot_id, t("cmd-system-ok", locale))

    @router.message(Command("system_clear"))
    async def system_clear_command(message: Message, bot_id: int) -> None:
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)

        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and message.bot and not await is_admin(message.bot, message.chat.id, user_id):
                await answer(message, bot_id, t("commands-group-admin-only", locale))
                return

        async with SessionLocal() as session:
            repo = ChatRepository(session)
            await repo.set_system(bot_id, message.chat.id, None)

        await answer(message, bot_id, t("cmd-system-clear-ok", locale))

    return router
