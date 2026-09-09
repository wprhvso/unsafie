import logging

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.types import Message

from unsafie.agent.runtime import handle
from unsafie.database import SessionLocal
from unsafie.database.models.chat import GroupMode
from unsafie.database.repositories.chat import ChatRepository
from unsafie.fluent import t
from unsafie.telegram.group import addressed_to_bot, clean_mention
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
    async def message_handler(message: Message, bot_id: int, update_db_id: int | None) -> None:
        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            async with SessionLocal() as session:
                chat_row = await ChatRepository(session).get(bot_id, message.chat.id)
            mode = (chat_row.group_mode if chat_row else None) or GroupMode.MENTIONS.value
            if mode == GroupMode.OFF.value:
                return
            if mode == GroupMode.MENTIONS.value:
                me = await message.bot.me() if message.bot else None
                username = me.username if me else None
                if not addressed_to_bot(message, bot_id, username):
                    return
                if message.text and username:
                    cleaned = clean_mention(message.text, username)
                    if cleaned != message.text:
                        message = message.model_copy(update={"text": cleaned}).as_(message.bot)

        logger.info(
            "bot=%s chat=%s(%s) msg=%s from=%s content_type=%s reply_to=%s",
            bot_id,
            message.chat.id,
            message.chat.type,
            message.message_id,
            message.from_user.id if message.from_user else None,
            message.content_type,
            message.reply_to_message.message_id if message.reply_to_message else None,
        )
        await handle(message, bot_id, update_db_id)

    return router
