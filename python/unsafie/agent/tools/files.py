import logging
import posixpath

from aiogram.exceptions import TelegramAPIError

from unsafie.agent.tools.base import ToolContext, current_turn, error, text
from unsafie.database.models.response import ResponseKind
from unsafie.mime import VIEWABLE, human_size, sniff_mime
from unsafie.telegram import sender
from unsafie.telegram.keyboard import ButtonsError, describe, parse_buttons

logger = logging.getLogger(__name__)

SEND_LIMIT = 50 * 1024 * 1024
PHOTO_LIMIT = 10 * 1024 * 1024
MEDIA = ("document", "photo", "video", "audio", "voice", "animation", "sticker")
MEDIA_MIME = {
    "photo": lambda m: m in VIEWABLE and m != "image/gif",
    "video": lambda m: m.startswith("video/"),
    "audio": lambda m: m.startswith("audio/"),
    "voice": lambda m: m in ("audio/ogg", "audio/mpeg", "audio/mp4"),
    "animation": lambda m: m in ("image/gif", "video/mp4"),
    "sticker": lambda m: m in ("image/webp", "image/png", "video/webm", "application/gzip"),
}


def pick_media(kind: str | None, as_photo: bool, mime: str, size: int) -> tuple[str, str | None]:
    media = (kind or "").strip().lower() or ("photo" if as_photo else "document")
    if media not in MEDIA:
        return "document", f"kind must be one of {' | '.join(MEDIA)}; sent as document"
    if media == "document":
        return media, None
    if media == "photo" and size > PHOTO_LIMIT:
        return "document", f"photo exceeds {human_size(PHOTO_LIMIT)}, sent as document"
    if not MEDIA_MIME[media](mime):
        return "document", f"cannot send {mime} as {media}, sent as document"
    return media, None


async def deliver(
    ctx: ToolContext,
    data: bytes,
    filename: str,
    *,
    caption: str | None = None,
    as_photo: bool = False,
    kind: str | None = None,
    buttons: str | None = None,
    silent: bool = False,
) -> dict:
    if not data:
        return error("the file is empty")
    if len(data) > SEND_LIMIT:
        return error(f"file is {human_size(len(data))}, Telegram limit is {human_size(SEND_LIMIT)}")
    name = posixpath.basename((filename or "").strip().replace("\\", "/")) or "file"
    try:
        markup = parse_buttons(buttons)
    except ButtonsError as e:
        return error(str(e))
    mime = sniff_mime(data, name)
    media, note = pick_media(kind, as_photo, mime, len(data))
    notes = [note] if note else []
    turn = await current_turn(ctx)
    try:
        response, sent_as = await sender.send_file(
            ctx.bot,
            bot_id=ctx.bot_id,
            chat_id=ctx.chat_id,
            data=data,
            filename=name,
            caption=caption or None,
            kind=ResponseKind.AGENT,
            turn=turn,
            media=media,
            reply_markup=markup,
            silent=silent,
        )
    except TelegramAPIError as e:
        logger.error("%s deliver %s failed error=%s", ctx.prefix, name, e)
        return error(f"Telegram rejected the file: {e}")
    if sent_as != media:
        notes.append(f"Telegram rejected it as {media}, sent as document")
    out = f"sent {sent_as} {name} ({mime}, {human_size(len(data))}) ids={response.message_ids}"
    if response.reply_to:
        out += f" as reply to {response.reply_to}"
    if markup is not None and markup.inline_keyboard:
        out += f" buttons: {describe(markup)}"
    if notes:
        out += "\n" + "\n".join(notes)
    return text(out)
