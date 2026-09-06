import logging

from aiogram import Router
from aiogram.types import Message, Update

from unsafie.agent.jobs import enqueue_update
from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


async def _is_unknown_command(message: Message) -> bool:
    text = message.text or ""
    if not text.startswith("/"):
        return False
    entities = message.entities or []
    if not any(e.type == "bot_command" and e.offset == 0 for e in entities):
        return False
    command = text.split(maxsplit=1)[0]
    if "@" in command and message.bot is not None:
        me = await message.bot.me()
        mention = command.split("@", 1)[1]
        if me.username and mention.lower() != me.username.lower():
            return False
    return True


def build_messages_router() -> Router:
    router = Router()

    @router.message(_is_unknown_command)
    async def unknown_command_handler(message: Message, bot_id: int) -> None:
        command = (message.text or "").split(maxsplit=1)[0]
        user_id = message.from_user.id if message.from_user else 0
        locale = await locale_for(user_id, message.from_user)
        await answer(message, bot_id, t("commands-unknown", locale, command=command))

    @router.message()
    async def message_handler(message: Message, bot_id: int, event_update: Update) -> None:
        logger.info(
            "bot=%s chat=%s(%s) msg=%s from=%s content_type=%s",
            bot_id,
            message.chat.id,
            message.chat.type,
            message.message_id,
            message.from_user.id if message.from_user else None,
            message.content_type,
        )
        await enqueue_update(bot_id, event_update)

    return router
