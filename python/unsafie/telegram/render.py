from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from aiogram.enums import MessageEntityType as E
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    MessageEntity,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    User,
)

from unsafie.scheduler.when import fmt_local, zone

_INLINE: dict[str, tuple[str, str]] = {
    E.BOLD: ("**", "**"),
    E.ITALIC: ("_", "_"),
    E.UNDERLINE: ("__", "__"),
    E.STRIKETHROUGH: ("~~", "~~"),
    E.SPOILER: ("||", "||"),
    E.CODE: ("`", "`"),
}
_QUOTES = {E.BLOCKQUOTE, E.EXPANDABLE_BLOCKQUOTE}


def _units(text: str) -> list[str]:
    units: list[str] = []
    for ch in text:
        units.append(ch)
        if ord(ch) > 0xFFFF:
            units.append("")
    return units


def _markers(entity: MessageEntity) -> tuple[str, str] | None:
    kind = entity.type
    if kind in _INLINE:
        return _INLINE[kind]
    if kind == E.PRE:
        return (f"```{entity.language or ''}\n", "\n```")
    if kind == E.TEXT_LINK and entity.url:
        return ("[", f"]({entity.url})")
    if kind == E.TEXT_MENTION and entity.user:
        return ("[", f"](tg://user?id={entity.user.id})")
    if kind in _QUOTES:
        return ("> ", "")
    return None


def to_markdown(text: str | None, entities: Sequence[MessageEntity] | None) -> str:
    if not text:
        return ""
    if not entities:
        return text
    units = _units(text)
    n = len(units)
    opens: dict[int, list[tuple[int, int, str]]] = {}
    closes: dict[int, list[tuple[int, int, str]]] = {}
    quote_edges: dict[int, int] = {}
    for order, entity in enumerate(entities):
        start = max(0, min(n, entity.offset))
        end = max(start, min(n, entity.offset + entity.length))
        if start == end:
            continue
        markers = _markers(entity)
        if markers is None:
            continue
        opens.setdefault(start, []).append((-(end - start), order, markers[0]))
        closes.setdefault(end, []).append((-start, end - start, markers[1]))
        if entity.type in _QUOTES:
            quote_edges[start] = quote_edges.get(start, 0) + 1
            quote_edges[end] = quote_edges.get(end, 0) - 1
    out: list[str] = []
    quote_depth = 0
    for pos in range(n + 1):
        for _, _, marker in sorted(closes.get(pos, ())):
            out.append(marker)
        for _, _, marker in sorted(opens.get(pos, ())):
            out.append(marker)
        quote_depth += quote_edges.get(pos, 0)
        if pos == n:
            break
        ch = units[pos]
        out.append(ch)
        if ch == "\n" and quote_depth > 0 and pos + 1 < n:
            out.append("> ")
    return "".join(out)


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None and v != "" and v != [] and v != {}}


def user_info(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return _clean(
        {
            "id": user.id,
            "username": user.username,
            "name": user.full_name,
            "is_bot": True if user.is_bot else None,
            "language": user.language_code,
        }
    )


def chat_info(chat: Chat | None) -> dict[str, Any] | None:
    if chat is None:
        return None
    return _clean(
        {"id": chat.id, "type": chat.type, "title": chat.title, "username": chat.username}
    )


def _origin(message: Message) -> dict[str, Any] | None:
    origin = message.forward_origin
    if origin is None:
        return None
    data: dict[str, Any] = {"date": origin.date.isoformat()}
    match origin:
        case MessageOriginUser():
            data["from"] = user_info(origin.sender_user)
        case MessageOriginHiddenUser():
            data["from"] = {"name": origin.sender_user_name}
        case MessageOriginChat():
            data["chat"] = chat_info(origin.sender_chat)
            data["signature"] = origin.author_signature
        case MessageOriginChannel():
            data["chat"] = chat_info(origin.chat)
            data["message_id"] = origin.message_id
            data["signature"] = origin.author_signature
    return _clean(data)


def _media(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if message.photo:
        best = message.photo[-1]
        data["photo"] = _clean(
            {
                "file_id": best.file_id,
                "width": best.width,
                "height": best.height,
                "file_size": best.file_size,
            }
        )
    if message.document:
        d = message.document
        data["document"] = _clean(
            {
                "file_id": d.file_id,
                "file_name": d.file_name,
                "mime_type": d.mime_type,
                "file_size": d.file_size,
            }
        )
    if message.sticker:
        s = message.sticker
        data["sticker"] = _clean(
            {
                "file_id": s.file_id,
                "emoji": s.emoji,
                "set_name": s.set_name,
                "animated": True if (s.is_animated or s.is_video) else None,
            }
        )
    for name in ("voice", "audio", "video", "video_note", "animation"):
        item = getattr(message, name, None)
        if item is None:
            continue
        data[name] = _clean(
            {
                "file_id": item.file_id,
                "duration": getattr(item, "duration", None),
                "mime_type": getattr(item, "mime_type", None),
                "file_name": getattr(item, "file_name", None),
                "title": getattr(item, "title", None),
                "performer": getattr(item, "performer", None),
                "file_size": getattr(item, "file_size", None),
            }
        )
    if message.location:
        data["location"] = {
            "latitude": message.location.latitude,
            "longitude": message.location.longitude,
        }
    if message.venue:
        data["venue"] = _clean({"title": message.venue.title, "address": message.venue.address})
    if message.contact:
        c = message.contact
        data["contact"] = _clean(
            {
                "phone_number": c.phone_number,
                "name": " ".join(p for p in (c.first_name, c.last_name) if p),
                "user_id": c.user_id,
            }
        )
    if message.poll:
        data["poll"] = {
            "question": message.poll.question,
            "options": [o.text for o in message.poll.options],
        }
    if message.dice:
        data["dice"] = {"emoji": message.dice.emoji, "value": message.dice.value}
    return data


def describe(message: Message, *, nested: bool = False) -> dict[str, Any]:
    text = message.text if message.text is not None else message.caption
    entities = message.entities if message.text is not None else message.caption_entities
    data: dict[str, Any] = {
        "message_id": message.message_id,
        "date": message.date.isoformat(),
        "from": user_info(message.from_user),
        "sender_chat": chat_info(message.sender_chat) if message.sender_chat else None,
        "edited": message.edit_date.isoformat() if message.edit_date else None,
        "forwarded": _origin(message),
        "text": to_markdown(text, entities),
    }
    media = _media(message)
    data.update(media)
    if not nested:
        data["chat"] = chat_info(message.chat)
        if message.is_topic_message and message.message_thread_id:
            data["thread_id"] = message.message_thread_id
        if message.media_group_id:
            data["media_group_id"] = message.media_group_id
        if message.reply_to_message is not None:
            data["reply_to"] = describe(message.reply_to_message, nested=True)
        elif message.external_reply is not None:
            data["reply_to"] = _clean(
                {
                    "external": True,
                    "chat": chat_info(message.external_reply.chat),
                    "message_id": message.external_reply.message_id,
                }
            )
        if message.quote is not None:
            data["quote"] = _clean(
                {
                    "text": to_markdown(message.quote.text, message.quote.entities),
                    "manual": True if message.quote.is_manual else None,
                }
            )
        if message.content_type not in ("text", *media.keys()) and not text:
            data["content_type"] = str(message.content_type)
    return _clean(data)


def describe_scheduled(task) -> dict[str, Any]:
    tz = zone(task.tz)
    return _clean(
        {
            "scheduled": _clean(
                {
                    "id": task.id,
                    "text": task.text,
                    "planned_for": fmt_local(task.next_run_at, tz),
                    "cron": task.cron,
                    "every_sec": task.interval_sec,
                    "run": task.runs + 1,
                    "origin_message_id": task.origin_message_id,
                }
            ),
            "date": datetime.now(UTC).astimezone(tz).isoformat(timespec="seconds"),
        }
    )


def describe_watch(watch, host, output: str, exit_code: int) -> dict[str, Any]:
    return _clean(
        {
            "watch": _clean(
                {
                    "id": watch.id,
                    "name": watch.name,
                    "host": host.alias,
                    "command": watch.command,
                    "condition": watch.condition,
                    "exit_code": exit_code,
                    "output": output[-3000:],
                    "origin_message_id": watch.origin_message_id,
                }
            ),
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )


def describe_callback(query: CallbackQuery) -> dict[str, Any]:
    message = query.message if isinstance(query.message, Message) else None
    button: dict[str, Any] = {"data": query.data}
    if message is not None and message.reply_markup is not None:
        for row in message.reply_markup.inline_keyboard:
            for b in row:
                if b.callback_data == query.data:
                    button["text"] = b.text
    return _clean(
        {
            "callback": _clean(
                {
                    "id": query.id,
                    "from": user_info(query.from_user),
                    "button": _clean(button),
                    "message_id": message.message_id if message else None,
                    "message_text": to_markdown(
                        message.text if message.text is not None else message.caption,
                        message.entities if message.text is not None else message.caption_entities,
                    )
                    if message
                    else None,
                }
            ),
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "chat": chat_info(message.chat) if message else None,
        }
    )
