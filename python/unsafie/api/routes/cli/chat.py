import base64
import binascii
import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BufferedInputFile,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputPollOption,
    ReactionTypeEmoji,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

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
DICE = ("🎲", "🎯", "🏀", "⚽", "🎳", "🎰")
REACTIONS = (
    "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 "
    "🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 🤷‍♂ 🤷 🤷‍♀ 😡"
).split()
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


class Reaction(BaseModel):
    emoji: str = ""
    big: bool = False
    chat_id: int | None = None


class Pin(BaseModel):
    unpin: bool = False
    silent: bool = False
    chat_id: int | None = None


class Forward(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    to: str
    duplicate: bool = Field(default=False, alias="copy")
    caption: str | None = None
    silent: bool = False
    from_chat_id: int | None = None


class Poll(BaseModel):
    question: str
    options: list[str]
    anonymous: bool = True
    multiple: bool = False
    quiz: bool = False
    correct: int | None = None
    explanation: str | None = None
    close_in: int | None = None
    reply_to: int | None = None
    chat_id: int | None = None
    turn: str | None = None


class Dice(BaseModel):
    emoji: str = "🎲"
    chat_id: int | None = None
    turn: str | None = None


class Location(BaseModel):
    latitude: float
    longitude: float
    title: str | None = None
    address: str | None = None
    chat_id: int | None = None
    turn: str | None = None


class Contact(BaseModel):
    phone: str
    first_name: str
    last_name: str | None = None
    chat_id: int | None = None
    turn: str | None = None


class AlbumItem(BaseModel):
    name: str
    data: str
    media: str = "photo"


class Album(BaseModel):
    items: list[AlbumItem]
    caption: str | None = None
    chat_id: int | None = None
    turn: str | None = None


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


async def _record(who: Chat, turn_id: str | None, message, content: str) -> dict:
    turn = await who.turn(turn_id)
    await sender.record(
        bot_id=who.bot_id or 0,
        chat_id=message.chat.id,
        turn=turn,
        content=content,
        ids=[message.message_id],
    )
    return {"message_ids": [message.message_id], "chat_id": message.chat.id}


@router.post("/reactions/{message_id}")
async def react(message_id: int, body: Reaction, who: Chat) -> dict:
    if body.emoji and body.emoji not in REACTIONS:
        raise HTTPException(400, "no such reaction; try " + " ".join(REACTIONS[:12]))
    bot = await who.bot()
    try:
        await bot.set_message_reaction(
            who.chat(body.chat_id),
            message_id,
            reaction=[ReactionTypeEmoji(emoji=body.emoji)] if body.emoji else [],
            is_big=body.big or None,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"message_id": message_id, "emoji": body.emoji or None}


@router.post("/pins/{message_id}")
async def pin(message_id: int, body: Pin, who: Chat) -> dict:
    bot = await who.bot()
    chat_id = who.chat(body.chat_id)
    try:
        if body.unpin:
            await bot.unpin_chat_message(chat_id, message_id or None)
        else:
            await bot.pin_chat_message(chat_id, message_id, disable_notification=body.silent)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"message_id": message_id, "pinned": not body.unpin}


@router.post("/forwards/{message_id}")
async def forward(message_id: int, body: Forward, who: Chat) -> dict:
    bot = await who.bot()
    source = who.chat(body.from_chat_id)
    target: int | str = body.to
    if isinstance(target, str) and target.lstrip("-").isdigit():
        target = int(target)
    try:
        if body.duplicate:
            sent = await bot.copy_message(
                target, source, message_id, caption=body.caption, disable_notification=body.silent
            )
            return {"message_ids": [sent.message_id], "chat_id": str(target), "copied": True}
        sent = await bot.forward_message(
            target, source, message_id, disable_notification=body.silent
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"message_ids": [sent.message_id], "chat_id": str(target), "copied": False}


@router.post("/polls")
async def poll(body: Poll, who: Chat) -> dict:
    if not 2 <= len(body.options) <= 10:
        raise HTTPException(400, "a poll needs between two and ten options")
    bot = await who.bot()
    try:
        sent = await bot.send_poll(
            who.chat(body.chat_id),
            question=body.question,
            options=[InputPollOption(text=option) for option in body.options],
            is_anonymous=body.anonymous,
            allows_multiple_answers=body.multiple,
            type="quiz" if body.quiz else "regular",
            correct_option_id=body.correct if body.quiz else None,
            explanation=body.explanation,
            open_period=body.close_in,
            reply_to_message_id=body.reply_to,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return await _record(who, body.turn, sent, f"poll: {body.question}")


@router.post("/dice")
async def dice(body: Dice, who: Chat) -> dict:
    if body.emoji not in DICE:
        raise HTTPException(400, f"emoji must be one of {' '.join(DICE)}")
    bot = await who.bot()
    try:
        sent = await bot.send_dice(who.chat(body.chat_id), emoji=body.emoji)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    answer = await _record(who, body.turn, sent, f"dice {body.emoji}")
    return {**answer, "value": sent.dice.value if sent.dice else None}


@router.post("/locations")
async def location(body: Location, who: Chat) -> dict:
    bot = await who.bot()
    try:
        if body.title:
            sent = await bot.send_venue(
                who.chat(body.chat_id),
                latitude=body.latitude,
                longitude=body.longitude,
                title=body.title,
                address=body.address or body.title,
            )
        else:
            sent = await bot.send_location(
                who.chat(body.chat_id), latitude=body.latitude, longitude=body.longitude
            )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return await _record(who, body.turn, sent, f"location {body.latitude},{body.longitude}")


@router.post("/contacts")
async def contact(body: Contact, who: Chat) -> dict:
    bot = await who.bot()
    try:
        sent = await bot.send_contact(
            who.chat(body.chat_id),
            phone_number=body.phone,
            first_name=body.first_name,
            last_name=body.last_name,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return await _record(who, body.turn, sent, f"contact {body.first_name}")


@router.post("/albums")
async def album(body: Album, who: Chat) -> dict:
    if not 2 <= len(body.items) <= 10:
        raise HTTPException(400, "an album holds between two and ten files")
    bot = await who.bot()
    media = []
    for index, item in enumerate(body.items):
        try:
            data = base64.b64decode(item.data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, f"{item.name}: data is not base64") from None
        payload = BufferedInputFile(data, filename=item.name)
        caption = body.caption if index == 0 else None
        kind = item.media or "photo"
        if kind == "video":
            media.append(InputMediaVideo(media=payload, caption=caption))
        elif kind == "document":
            media.append(InputMediaDocument(media=payload, caption=caption))
        else:
            media.append(InputMediaPhoto(media=payload, caption=caption))
    try:
        sent = await bot.send_media_group(who.chat(body.chat_id), media=media)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    turn = await who.turn(body.turn)
    ids = [message.message_id for message in sent]
    await sender.record(
        bot_id=who.bot_id or 0,
        chat_id=sent[0].chat.id,
        turn=turn,
        content=f"album of {len(ids)}",
        ids=ids,
    )
    return {"message_ids": ids}
