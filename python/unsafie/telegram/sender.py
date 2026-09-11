import functools
import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    MessageEntity,
    ReplyParameters,
)
from llmmd import process_markdown

from unsafie import events, telemetry
from unsafie.agent import live
from unsafie.database import SessionLocal
from unsafie.database.models.response import Response, ResponseKind
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.response import ResponseRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.settings import settings
from unsafie.telegram.retry import retry
from unsafie.telemetry import attrs

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


async def reply_target(turn: Turn) -> int | None:
    async with SessionLocal() as session:
        return await TurnRepository(session).reply_target(turn, settings.lineage_depth)


def chunks_of(markdown: str) -> list[Any]:
    try:
        return list(process_markdown(markdown)) or [{"text": markdown, "entities": []}]
    except Exception:
        logger.warning("markdown processing failed, falling back to plain text")
        parts = []
        limit = 4096
        text = markdown or ""
        for i in range(0, max(1, len(text)), limit):
            parts.append({"text": text[i : i + limit], "entities": []})
        return parts


def _entities(chunk: dict) -> list[MessageEntity]:
    return [MessageEntity(**e) for e in chunk["entities"]]


def _reply_params(reply_to: int | None) -> ReplyParameters | None:
    if reply_to is None:
        return None
    return ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)


def _preview_options(preview: bool) -> LinkPreviewOptions | None:
    return None if preview else LinkPreviewOptions(is_disabled=True)


def _preview(text: str, limit: int = 120) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


async def _record(
    *,
    bot_id: int,
    chat_id: int,
    turn: Turn | None,
    kind: ResponseKind,
    content: str,
    ids: list[int],
    reply_to: int | None,
) -> Response:
    turn_id: UUID | None = turn.id if turn else None
    async with SessionLocal() as session:
        response = await ResponseRepository(session).add(
            bot_id=bot_id,
            chat_id=chat_id,
            turn_id=turn_id,
            kind=kind,
            content=content,
            message_ids=ids,
            reply_to=reply_to,
        )
    events.publish(
        "message.out",
        bot_id=bot_id,
        chat_id=chat_id,
        message_ids=ids,
        kind=str(kind),
        turn_id=str(turn_id) if turn_id else None,
        text=_preview(content),
    )
    live.emit(
        turn_id,
        "reply.sent",
        kind=str(kind),
        message_ids=ids,
        reply_to=reply_to,
        text=live.clip(content)[0],
    )
    logger.info(
        "bot=%s chat=%s turn=%s sent kind=%s messages=%s reply_to=%s",
        bot_id,
        chat_id,
        turn_id,
        kind,
        ids,
        reply_to,
    )
    return response


async def _send_chunks(
    bot: Bot,
    prefix: str,
    chat_id: int,
    chunks: list[dict],
    reply_to: int | None,
    reply_markup: InlineKeyboardMarkup | None,
    silent: bool = False,
    preview: bool = True,
) -> list[int]:
    ids: list[int] = []
    last = len(chunks) - 1
    for i, chunk in enumerate(chunks):
        msg = await retry(
            functools.partial(
                bot.send_message,
                chat_id,
                chunk["text"],
                entities=_entities(chunk),
                reply_parameters=_reply_params(reply_to) if i == 0 else None,
                reply_markup=reply_markup if i == last else None,
                disable_notification=silent or None,
                link_preview_options=_preview_options(preview),
            ),
            f"{prefix} send chunk {i + 1}/{len(chunks)}",
        )
        ids.append(msg.message_id)
    return ids


async def send(
    bot: Bot,
    *,
    bot_id: int,
    chat_id: int,
    markdown: str,
    kind: ResponseKind,
    turn: Turn | None = None,
    reply_to: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    silent: bool = False,
    preview: bool = True,
) -> Response:
    prefix = f"bot={bot_id} chat={chat_id} turn={turn.id if turn else None}"
    with telemetry.span(
        "tg.send",
        kind=telemetry.PRODUCER,
        attributes={
            attrs.BOT_ID: bot_id,
            attrs.CHAT_ID: chat_id,
            attrs.TURN_ID: str(turn.id) if turn else None,
            attrs.TG_KIND: str(kind),
            attrs.TG_SILENT: silent,
            attrs.PROMPT: telemetry.content(markdown),
        },
    ) as span:
        chunks = chunks_of(markdown)
        if turn is not None and reply_to is None:
            reply_to = await reply_target(turn)
        ids = await _send_chunks(
            bot, prefix, chat_id, chunks, reply_to, reply_markup, silent, preview,
        )
        telemetry.set_attrs(
            span,
            {attrs.TG_CHUNKS: len(chunks), attrs.TG_MESSAGE_IDS: ids, attrs.MESSAGE_ID: reply_to},
        )
        return await _record(
            bot_id=bot_id,
            chat_id=chat_id,
            turn=turn,
            kind=kind,
            content=markdown,
            ids=ids,
            reply_to=reply_to,
        )


@telemetry.traced("tg.send_file", kind=telemetry.PRODUCER)
async def send_file(
    bot: Bot,
    *,
    bot_id: int,
    chat_id: int,
    data: bytes,
    filename: str,
    caption: str | None,
    kind: ResponseKind,
    turn: Turn | None = None,
    reply_to: int | None = None,
    media: str = "document",
    reply_markup: InlineKeyboardMarkup | None = None,
    silent: bool = False,
) -> tuple[Response, str]:
    prefix = f"bot={bot_id} chat={chat_id} turn={turn.id if turn else None}"
    telemetry.annotate(
        **{
            attrs.BOT_ID: bot_id,
            attrs.CHAT_ID: chat_id,
            attrs.TURN_ID: str(turn.id) if turn else None,
            attrs.TG_KIND: str(kind),
            attrs.FILE_NAME: filename,
            attrs.FILE_BYTES: len(data),
            attrs.FILE_MEDIA: media,
        },
    )
    if turn is not None and reply_to is None:
        reply_to = await reply_target(turn)
    chunks = chunks_of(caption) if caption else []
    inline = len(chunks) == 1 and len(chunks[0]["text"]) <= CAPTION_LIMIT
    head = chunks[0] if inline else None
    tail = [] if inline else chunks
    file = BufferedInputFile(data, filename=filename)
    kwargs: dict = {
        "reply_parameters": _reply_params(reply_to),
        "reply_markup": reply_markup if not tail else None,
        "disable_notification": silent or None,
    }
    if media != "sticker":
        kwargs["caption"] = head["text"] if head else None
        kwargs["caption_entities"] = _entities(head) if head else None
    elif head:
        tail = chunks
    senders = {
        "photo": bot.send_photo,
        "video": bot.send_video,
        "audio": bot.send_audio,
        "voice": bot.send_voice,
        "animation": bot.send_animation,
        "sticker": bot.send_sticker,
    }
    msg: Message | None = None
    if media in senders:
        try:
            msg = await retry(
                functools.partial(senders[media], chat_id, file, **kwargs),
                f"{prefix} send {media} {filename}",
            )
        except TelegramBadRequest as e:
            logger.info("%s %s %s rejected (%s), sending as document", prefix, media, filename, e)
            media = "document"
            if inline:
                kwargs["caption"] = head["text"] if head else None
                kwargs["caption_entities"] = _entities(head) if head else None
                tail = []
                kwargs["reply_markup"] = reply_markup
            else:
                kwargs["caption"] = None
                kwargs["caption_entities"] = None
                tail = chunks
    if msg is None:
        media = "document"
        msg = await retry(
            functools.partial(bot.send_document, chat_id, file, **kwargs),
            f"{prefix} send document {filename}",
        )
    ids = [msg.message_id]
    if tail:
        ids += await _send_chunks(bot, prefix, chat_id, tail, None, reply_markup)
    content = f"[{media} {filename}, {len(data)} bytes]"
    if caption:
        content += f"\n{caption}"
    telemetry.annotate(**{attrs.FILE_MEDIA: media, attrs.TG_MESSAGE_IDS: ids})
    response = await _record(
        bot_id=bot_id,
        chat_id=chat_id,
        turn=turn,
        kind=kind,
        content=content,
        ids=ids,
        reply_to=reply_to,
    )
    return response, media


async def record(
    *,
    bot_id: int,
    chat_id: int,
    turn: Turn | None,
    content: str,
    ids: list[int],
    reply_to: int | None = None,
    kind: ResponseKind = ResponseKind.AGENT,
) -> Response:
    return await _record(
        bot_id=bot_id,
        chat_id=chat_id,
        turn=turn,
        kind=kind,
        content=content,
        ids=ids,
        reply_to=reply_to,
    )


@telemetry.traced("tg.edit", kind=telemetry.PRODUCER)
async def edit(
    bot: Bot,
    *,
    bot_id: int,
    chat_id: int,
    message_id: int,
    markdown: str | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> str:
    prefix = f"bot={bot_id} chat={chat_id} msg={message_id}"
    telemetry.annotate(
        **{attrs.BOT_ID: bot_id, attrs.CHAT_ID: chat_id, attrs.MESSAGE_ID: message_id},
    )
    if markdown is None:
        try:
            await retry(
                functools.partial(
                    bot.edit_message_reply_markup,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                ),
                f"{prefix} edit markup",
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return "buttons"
            raise
        return "buttons"
    chunks = chunks_of(markdown)
    if len(chunks) != 1:
        msg = "text does not fit into one message; send a new one"
        raise ValueError(msg)
    chunk = chunks[0]
    try:
        await retry(
            functools.partial(
                bot.edit_message_text,
                chunk["text"],
                chat_id=chat_id,
                message_id=message_id,
                entities=_entities(chunk),
                reply_markup=reply_markup,
            ),
            f"{prefix} edit text",
        )
        what = "text"
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return "text"
        if "no text in the message" not in err:
            raise
        if len(chunk["text"]) > CAPTION_LIMIT:
            msg = f"a caption cannot exceed {CAPTION_LIMIT} characters"
            raise ValueError(msg) from e
        try:
            await retry(
                functools.partial(
                    bot.edit_message_caption,
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=chunk["text"],
                    caption_entities=_entities(chunk),
                    reply_markup=reply_markup,
                ),
                f"{prefix} edit caption",
            )
        except TelegramBadRequest as cap_err:
            if "message is not modified" in str(cap_err).lower():
                return "caption"
            raise
        what = "caption"
    async with SessionLocal() as session:
        await ResponseRepository(session).set_content(bot_id, chat_id, message_id, markdown)
    return what


@telemetry.traced("tg.delete", kind=telemetry.PRODUCER)
async def delete(bot: Bot, *, bot_id: int, chat_id: int, message_id: int) -> None:
    telemetry.annotate(
        **{attrs.BOT_ID: bot_id, attrs.CHAT_ID: chat_id, attrs.MESSAGE_ID: message_id},
    )
    await retry(
        functools.partial(bot.delete_message, chat_id=chat_id, message_id=message_id),
        f"bot={bot_id} chat={chat_id} msg={message_id} delete",
    )
    async with SessionLocal() as session:
        await ResponseRepository(session).forget(bot_id, chat_id, message_id)


async def answer(
    message: Message, bot_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None,
) -> Response:
    assert message.bot is not None
    return await send(
        message.bot,
        bot_id=bot_id,
        chat_id=message.chat.id,
        markdown=text,
        kind=ResponseKind.SYSTEM,
        reply_to=message.message_id,
        reply_markup=reply_markup,
    )
