import re

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, MessageEntityType
from aiogram.types import Message

from unsafie.database.models.chat import GroupMode

DEFAULT_GROUP_MODE = GroupMode.MENTIONS


def _slice_utf16(text: str, offset: int, length: int) -> str:
    encoded = text.encode("utf-16-le")
    start = offset * 2
    end = (offset + length) * 2
    return encoded[start:end].decode("utf-16-le", errors="replace")


def addressed_to_bot(message: Message, bot_id: int, username: str | None) -> bool:
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and reply.from_user.id == bot_id:
        if getattr(reply, "forum_topic_created", None) is None:
            return True

    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    for entity in entities:
        if entity.type == MessageEntityType.TEXT_MENTION:
            if entity.user and entity.user.id == bot_id:
                return True
        elif entity.type == MessageEntityType.MENTION and username:
            entity_text = _slice_utf16(text, entity.offset, entity.length)
            if entity_text.casefold() == f"@{username}".casefold():
                return True
        elif entity.type == MessageEntityType.BOT_COMMAND and entity.offset == 0 and username:
            cmd_text = _slice_utf16(text, entity.offset, entity.length)
            if "@" in cmd_text and cmd_text.split("@", 1)[1].casefold() == username.casefold():
                return True

    return False


def clean_mention(
    text: str | None,
    username: str | None,
    entities: list | None = None,
) -> tuple[str | None, list | None]:
    if not text or not username:
        return text, entities
    encoded = text.encode("utf-16-le")
    target_idx = None
    target_entity = None
    if entities:
        for idx, e in enumerate(entities):
            if getattr(e, "type", None) in ("mention", MessageEntityType.MENTION):
                slice_bytes = encoded[e.offset * 2 : (e.offset + e.length) * 2]
                slice_str = slice_bytes.decode("utf-16-le", errors="replace")
                if slice_str.casefold() == f"@{username}".casefold():
                    target_idx = idx
                    target_entity = e
                    break

    if target_entity is not None and entities is not None:
        cut_start = target_entity.offset
        cut_end = target_entity.offset + target_entity.length
        prefix_slice = encoded[: cut_start * 2].decode("utf-16-le", errors="replace")
        if not prefix_slice.strip():
            suffix_bytes = encoded[cut_end * 2 :]
            suffix_str = suffix_bytes.decode("utf-16-le", errors="replace")
            stripped_suffix = suffix_str.lstrip(" ")
            ws_removed = len(suffix_str) - len(stripped_suffix)
            cut_end += ws_removed
            cut_start = 0

        new_encoded = encoded[: cut_start * 2] + encoded[cut_end * 2 :]
        new_text = new_encoded.decode("utf-16-le", errors="replace")
        cut_units = cut_end - cut_start

        new_entities = []
        for idx, e in enumerate(entities):
            if idx == target_idx:
                continue
            if e.offset >= cut_end:
                new_entities.append(e.model_copy(update={"offset": max(0, e.offset - cut_units)}))
            elif e.offset + e.length <= cut_start:
                new_entities.append(e)
        return (new_text or text), new_entities

    pattern = re.compile(rf"@{re.escape(username)}\b", re.IGNORECASE)
    cleaned = pattern.sub("", text).strip()
    return (cleaned or text), entities


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    else:
        return member.status in (
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        )
