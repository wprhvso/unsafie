import re

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, MessageEntityType
from aiogram.types import Message

from unsafie.database.models.chat import GroupMode

DEFAULT_GROUP_MODE = GroupMode.MENTIONS


def addressed_to_bot(message: Message, bot_id: int, username: str | None) -> bool:
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and reply.from_user.id == bot_id:
        return True

    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    for entity in entities:
        if entity.type == MessageEntityType.TEXT_MENTION:
            if entity.user and entity.user.id == bot_id:
                return True
        elif entity.type == MessageEntityType.MENTION and username:
            entity_text = text[entity.offset : entity.offset + entity.length]
            if entity_text.casefold() == f"@{username}".casefold():
                return True
        elif entity.type == MessageEntityType.BOT_COMMAND and entity.offset == 0 and username:
            cmd_text = text[entity.offset : entity.offset + entity.length]
            if "@" in cmd_text and cmd_text.split("@", 1)[1].casefold() == username.casefold():
                return True

    return False


def clean_mention(text: str | None, username: str | None) -> str | None:
    if not text or not username:
        return text
    pattern = re.compile(rf"@{re.escape(username)}\b", re.IGNORECASE)
    cleaned = pattern.sub("", text).strip()
    return cleaned if cleaned else text


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        )
    except Exception:
        return False
