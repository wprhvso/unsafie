from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer


def build_start_router() -> Router:
    router = Router()

    @router.message(Command("start", "help"))
    async def start_handler(message: Message, bot_id: int) -> None:
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)
        await answer(message, bot_id, t("commands-start", locale))

    return router
