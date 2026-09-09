from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.database import SessionLocal
from unsafie.database.repositories.chat import ChatRepository
from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer


def build_system_router() -> Router:
    router = Router()

    @router.message(Command("system"))
    async def system_command(message: Message, command: CommandObject, bot_id: int) -> None:
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)
        prompt = (command.args or "").strip()

        async with SessionLocal() as session:
            repo = ChatRepository(session)
            if not prompt:
                chat = await repo.get(bot_id, message.chat.id)
                if chat and chat.system:
                    text = f"{t('cmd-system-ok', locale)}:\n\n<code>{chat.system}</code>\n\n{t('cmd-system-help', locale)}"
                else:
                    text = t("cmd-system-help", locale)
                await answer(message, bot_id, text)
                return

            await repo.set_system(bot_id, message.chat.id, prompt)
            await answer(message, bot_id, t("cmd-system-ok", locale))

    @router.message(Command("system_clear"))
    async def system_clear_command(message: Message, bot_id: int) -> None:
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)

        async with SessionLocal() as session:
            repo = ChatRepository(session)
            await repo.set_system(bot_id, message.chat.id, None)

        await answer(message, bot_id, t("cmd-system-clear-ok", locale))

    return router
