import base64
import binascii
import logging

from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from unsafie.agent import live
from unsafie.api.routes.cli.deps import Chat
from unsafie.database.models.response import ResponseKind
from unsafie.mime import human_size, sniff_mime
from unsafie.telegram import sender
from unsafie.telegram.keyboard import ButtonsError, parse_buttons

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["cli"])

MAX_FILE = 20 * 1024 * 1024
MEDIA = ("document", "photo", "video", "audio", "voice", "animation", "sticker")
ACTIONS = frozenset(
    {
        "typing",
        "upload_photo",
        "record_video",
        "upload_video",
        "record_voice",
        "upload_voice",
        "upload_document",
        "choose_sticker",
        "find_location",
        "record_video_note",
        "upload_video_note",
    }
)


class Message(BaseModel):
    text: str = Field(min_length=1)
    chat_id: int | None = None
    reply_to: int | None = None
    buttons: str | None = None
    silent: bool = False
    turn: str | None = None


class Upload(BaseModel):
    name: str
    data: str
    caption: str | None = None
    media: str = "document"
    chat_id: int | None = None
    silent: bool = False
    turn: str | None = None


class Edit(BaseModel):
    text: str | None = None
    buttons: str | None = None
    chat_id: int | None = None


class Note(BaseModel):
    text: str
    turn: str | None = None


class Action(BaseModel):
    action: str = "typing"
    chat_id: int | None = None


def _markup(raw: str | None):
    try:
        return parse_buttons(raw)
    except ButtonsError as bad:
        raise HTTPException(400, str(bad)) from None


@router.post("/messages")
async def say(body: Message, who: Chat) -> dict:
    bot = await who.bot()
    turn = await who.turn(body.turn)
    try:
        response = await sender.send(
            bot,
            bot_id=who.bot_id or 0,
            chat_id=who.chat(body.chat_id),
            markdown=body.text,
            kind=ResponseKind.AGENT,
            turn=turn,
            reply_to=body.reply_to,
            reply_markup=_markup(body.buttons),
            silent=body.silent,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"message_ids": response.message_ids, "reply_to": response.reply_to}


@router.post("/files")
async def upload(body: Upload, who: Chat) -> dict:
    try:
        data = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "data is not base64") from None
    if not data:
        raise HTTPException(400, "the file is empty")
    if len(data) > MAX_FILE:
        raise HTTPException(413, f"{human_size(len(data))} is over the {human_size(MAX_FILE)} limit")
    if body.media not in MEDIA:
        raise HTTPException(400, f"media must be one of {', '.join(MEDIA)}")
    bot = await who.bot()
    turn = await who.turn(body.turn)
    try:
        response, sent_as = await sender.send_file(
            bot,
            bot_id=who.bot_id or 0,
            chat_id=who.chat(body.chat_id),
            data=data,
            filename=body.name,
            caption=body.caption,
            kind=ResponseKind.AGENT,
            turn=turn,
            media=body.media,
            silent=body.silent,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {
        "message_ids": response.message_ids,
        "sent_as": sent_as,
        "mime": sniff_mime(data, body.name),
        "bytes": len(data),
    }


@router.post("/messages/{message_id}")
async def edit(message_id: int, body: Edit, who: Chat) -> dict:
    bot = await who.bot()
    try:
        what = await sender.edit(
            bot,
            bot_id=who.bot_id or 0,
            chat_id=who.chat(body.chat_id),
            message_id=message_id,
            markdown=body.text,
            reply_markup=_markup(body.buttons),
        )
    except ValueError as bad:
        raise HTTPException(400, str(bad)) from None
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"edited": what, "message_id": message_id}


@router.delete("/messages/{message_id}")
async def drop(message_id: int, who: Chat, chat_id: int | None = None) -> dict:
    bot = await who.bot()
    try:
        await sender.delete(
            bot, bot_id=who.bot_id or 0, chat_id=who.chat(chat_id), message_id=message_id
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"deleted": message_id}


@router.post("/notes")
async def note(body: Note, who: Chat) -> dict:
    turn = await who.turn(body.turn)
    if turn is None:
        raise HTTPException(400, "no turn to write into: pass turn=<id> or set UNSAFIE_TURN")
    live.emit(turn.id, "note", text=body.text, source=who.machine or "cli")
    return {"noted": True, "turn": str(turn.id)}


@router.post("/actions")
async def action(body: Action, who: Chat) -> dict:
    if body.action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {', '.join(sorted(ACTIONS))}")
    bot = await who.bot()
    try:
        await bot.send_chat_action(who.chat(body.chat_id), body.action)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"action": body.action}
