import asyncio
import base64
import binascii
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
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
from sqlalchemy import select

from unsafie import cluster
from unsafie.agent import live
from unsafie.api.routes.cli.deps import Chat
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.models.update import Update
from unsafie.database.repositories.chat import ChatRepository
from unsafie.database.repositories.response import ResponseRepository
from unsafie.mime import human_size, sniff_mime
from unsafie.telegram import sender
from unsafie.telegram.keyboard import ButtonsError, parse_buttons

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["cli"])

MAX_FILE = 20 * 1024 * 1024
MEDIA = ("document", "photo", "video", "audio", "voice", "animation", "sticker")
DICE = ("🎲", "🎯", "🏀", "⚽", "🎳", "🎰")
REACTIONS = ["👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤\u200d🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨\u200d💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷\u200d♂", "🤷", "🤷\u200d♀", "😡"]
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
    },
)


class Message(BaseModel):
    text: str = Field(min_length=1)
    chat_id: int | None = None
    reply_to: int | None = None
    buttons: str | None = None
    silent: bool = False
    turn: str | None = None
    idempotency_key: str | None = None


class Moderation(BaseModel):
    chat_id: int | None = None
    until: str | None = None
    revoke: bool = False
    undo: bool = False


class Invite(BaseModel):
    chat_id: int | None = None
    name: str | None = None
    member_limit: int | None = None
    expires_in: str | None = None
    join_request: bool = False


def _until(value: str | None):
    from datetime import UTC, datetime, timedelta

    from unsafie.scheduler.when import WhenError, duration

    if not value:
        return None
    try:
        return datetime.now(UTC) + timedelta(seconds=duration(value))
    except WhenError:
        raise HTTPException(400, f"'{value}' is not a duration: use 10m, 1h, 7d") from None


def _hit(hit) -> dict:
    return {
        "who": hit.who,
        "message_id": hit.message_id,
        "user_id": hit.user_id,
        "name": hit.name,
        "at": hit.when,
        "text": hit.body,
        "reply_to": hit.reply_to,
    }


class Upload(BaseModel):
    name: str
    data: str
    caption: str | None = None
    media: str = "document"
    chat_id: int | None = None
    silent: bool = False
    turn: str | None = None
    idempotency_key: str | None = None


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


def _trigger_bot_reply_turn(
    *,
    bot: Bot,
    bot_id: int,
    chat_id: int,
    user_id: int,
    reply_to: int,
    text: str,
    sent_message_id: int | None,
    target_content: str,
    target_created_at: datetime | None,
) -> None:
    async def _runner() -> None:
        from unsafie.agent.runtime import dispatch

        async with SessionLocal() as session:
            chat_row = await ChatRepository(session).get(bot_id, chat_id)
            latest_update = await session.scalar(
                select(Update)
                .where(Update.bot_id == bot_id, Update.user_id == user_id)
                .order_by(Update.id.desc())
                .limit(1),
            )

        chat_data: dict[str, Any] = {"id": chat_id}
        if chat_row:
            if chat_row.type:
                chat_data["type"] = chat_row.type
            if chat_row.title:
                chat_data["title"] = chat_row.title
            if chat_row.username:
                chat_data["username"] = chat_row.username

        from_data = None
        if latest_update and "message" in latest_update.payload and "from" in latest_update.payload["message"]:
            from_data = latest_update.payload["message"]["from"]
        if not from_data:
            from_data = {"id": user_id}

        def _prompt(in_context: bool) -> str:
            data: dict[str, Any] = {
                "message_id": sent_message_id,
                "date": datetime.now(UTC).isoformat(),
                "from": from_data,
                "text": text,
                "chat": chat_data,
                "reply_to": {
                    "message_id": reply_to,
                    "date": target_created_at.isoformat() if target_created_at else None,
                    "from": {"is_bot": True},
                    "text": target_content,
                    "in_context": in_context,
                },
            }
            return json.dumps(data, ensure_ascii=False)

        try:
            await dispatch(
                bot,
                bot_id=bot_id,
                chat_id=chat_id,
                user_id=user_id,
                reply_to=reply_to,
                update_db_id=None,
                build_prompt=_prompt,
                turn_reply_to=sent_message_id,
                what=f"bot-reply={sent_message_id or reply_to}",
            )
        except Exception:
            logger.exception(
                "bot=%s chat=%s failed to dispatch turn for reply_to=%s",
                bot_id,
                chat_id,
                reply_to,
            )

    task = asyncio.create_task(_runner(), name=f"bot-reply:{sent_message_id or reply_to}")
    _ = task


@router.post("/messages")
async def say(body: Message, who: Chat) -> dict:
    bot = await who.bot()
    turn = await who.turn(body.turn)
    bot_id = who.bot_id or 0
    target_chat = await who.target_chat(body.chat_id)

    idemp_key = body.idempotency_key
    if not idemp_key and body.turn:
        raw = f"{body.text}:{body.reply_to}:{body.buttons}"
        idemp_key = f"{body.turn}:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    cache_k = cluster.key("idemp", "msg", bot_id, target_chat, idemp_key) if idemp_key else None
    if cache_k:
        try:
            redis = cluster.client()
            cached = await redis.get(cache_k)
            if cached:
                logger.info("idempotent message replay key=%s", idemp_key)
                return json.loads(cached)
        except Exception:
            pass

    try:
        response = await sender.send(
            bot,
            bot_id=bot_id,
            chat_id=target_chat,
            markdown=body.text,
            kind=ResponseKind.AGENT,
            turn=turn,
            reply_to=body.reply_to,
            reply_markup=_markup(body.buttons),
            silent=body.silent,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None



    result = {"message_ids": response.message_ids, "reply_to": response.reply_to}
    if cache_k:
        try:
            redis = cluster.client()
            await redis.set(cache_k, json.dumps(result, ensure_ascii=False), ex=86400)
        except Exception:
            pass

    return result


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
    bot_id = who.bot_id or 0
    target_chat = await who.target_chat(body.chat_id)

    idemp_key = body.idempotency_key
    if not idemp_key and body.turn:
        raw = f"{body.name}:{len(data)}:{body.caption}"
        idemp_key = f"{body.turn}:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    cache_k = cluster.key("idemp", "file", bot_id, target_chat, idemp_key) if idemp_key else None
    if cache_k:
        try:
            redis = cluster.client()
            cached = await redis.get(cache_k)
            if cached:
                logger.info("idempotent file replay key=%s", idemp_key)
                return json.loads(cached)
        except Exception:
            pass

    try:
        response, sent_as = await sender.send_file(
            bot,
            bot_id=bot_id,
            chat_id=target_chat,
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

    result = {
        "message_ids": response.message_ids,
        "sent_as": sent_as,
        "mime": sniff_mime(data, body.name),
        "bytes": len(data),
    }
    if cache_k:
        try:
            redis = cluster.client()
            await redis.set(cache_k, json.dumps(result, ensure_ascii=False), ex=86400)
        except Exception:
            pass

    return result


@router.post("/messages/{message_id}")
async def edit(message_id: int, body: Edit, who: Chat) -> dict:
    bot = await who.bot()
    target_chat = await who.target_chat(body.chat_id)
    try:
        what = await sender.edit(
            bot,
            bot_id=who.bot_id or 0,
            chat_id=target_chat,
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
    target_chat = await who.target_chat(chat_id)
    await who.ensure_admin(target_chat)
    try:
        await sender.delete(
            bot, bot_id=who.bot_id or 0, chat_id=target_chat, message_id=message_id,
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
    target_chat = await who.target_chat(body.chat_id)
    try:
        await bot.send_chat_action(target_chat, body.action)
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
    target_chat = await who.target_chat(body.chat_id)
    try:
        await bot.set_message_reaction(
            target_chat,
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
    chat_id = await who.target_chat(body.chat_id)
    await who.ensure_admin(chat_id)
    try:
        if body.unpin:
            await bot.unpin_chat_message(chat_id, message_id=message_id or None)
        else:
            await bot.pin_chat_message(chat_id, message_id, disable_notification=body.silent)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"message_id": message_id, "pinned": not body.unpin}


@router.post("/forwards/{message_id}")
async def forward(message_id: int, body: Forward, who: Chat) -> dict:
    bot = await who.bot()
    source = await who.target_chat(body.from_chat_id)
    target: int | str
    if body.to.lstrip("-").isdigit():
        target = int(body.to)
    else:
        if who.chat_id is not None:
            raise HTTPException(403, "cross-chat access is forbidden for this token")
        try:
            resolved_chat = await bot.get_chat(body.to)
            target = await who.target_chat(resolved_chat.id)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(403, f"cannot access target chat: {e}") from None
    target = await who.target_chat(target)
    try:
        if body.duplicate:
            sent = await bot.copy_message(
                target, source, message_id, caption=body.caption, disable_notification=body.silent,
            )
            return {"message_ids": [sent.message_id], "chat_id": str(target), "copied": True}
        sent = await bot.forward_message(
            target, source, message_id, disable_notification=body.silent,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"message_ids": [sent.message_id], "chat_id": str(target), "copied": False}


@router.post("/polls")
async def poll(body: Poll, who: Chat) -> dict:
    if not 2 <= len(body.options) <= 10:
        raise HTTPException(400, "a poll needs between two and ten options")
    bot = await who.bot()
    target_chat = await who.target_chat(body.chat_id)
    try:
        sent = await bot.send_poll(
            target_chat,
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
    target_chat = await who.target_chat(body.chat_id)
    try:
        sent = await bot.send_dice(target_chat, emoji=body.emoji)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    answer = await _record(who, body.turn, sent, f"dice {body.emoji}")
    return {**answer, "value": sent.dice.value if sent.dice else None}


@router.post("/locations")
async def location(body: Location, who: Chat) -> dict:
    bot = await who.bot()
    target_chat = await who.target_chat(body.chat_id)
    try:
        if body.title:
            sent = await bot.send_venue(
                target_chat,
                latitude=body.latitude,
                longitude=body.longitude,
                title=body.title,
                address=body.address or body.title,
            )
        else:
            sent = await bot.send_location(
                target_chat, latitude=body.latitude, longitude=body.longitude,
            )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return await _record(who, body.turn, sent, f"location {body.latitude},{body.longitude}")


@router.post("/contacts")
async def contact(body: Contact, who: Chat) -> dict:
    bot = await who.bot()
    target_chat = await who.target_chat(body.chat_id)
    try:
        sent = await bot.send_contact(
            target_chat,
            phone_number=body.phone,
            first_name=body.first_name,
            last_name=body.last_name,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return await _record(who, body.turn, sent, f"contact {body.first_name}")


@router.get("/history/search")
async def history_search(
    who: Chat,
    query: str,
    chat_id: int | None = None,
    kind: str = "any",
    since: int | None = None,
    until: int | None = None,
    limit: int = 20,
) -> dict:
    from unsafie.database import SessionLocal
    from unsafie.database.repositories.history import HistoryRepository

    if who.bot_id is None:
        raise HTTPException(400, "this token is not bound to a bot")
    target_chat = await who.target_chat(chat_id)
    async with SessionLocal() as session:
        hits, how = await HistoryRepository(session).search(
            who.bot_id,
            target_chat,
            query,
            who=kind,
            since=since,
            until=until,
            limit=max(1, min(limit, 50)),
        )
    return {"matched_by": how, "hits": [_hit(hit) for hit in hits]}


@router.get("/history")
async def history_get(
    who: Chat, chat_id: int | None = None, message_id: int | None = None, around: int = 5, limit: int = 20, before: int | None = None,
) -> dict:
    from unsafie.database import SessionLocal
    from unsafie.database.repositories.history import HistoryRepository

    if who.bot_id is None:
        raise HTTPException(400, "this token is not bound to a bot")
    target_chat = await who.target_chat(chat_id)
    async with SessionLocal() as session:
        repository = HistoryRepository(session)
        if message_id:
            hits = await repository.around(who.bot_id, chat_id, message_id, max(1, min(around, 30)))
        else:
            hits = await repository.recent(who.bot_id, chat_id, max(1, min(limit, 100)), before)
    return {"hits": [_hit(hit) for hit in hits]}


@router.get("/info")
async def chat_info(who: Chat, chat_id: int | None = None) -> dict:
    bot = await who.bot()
    target_chat = await who.target_chat(chat_id)
    try:
        found = await bot.get_chat(target_chat)
        members = await bot.get_chat_member_count(target_chat)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {
        "id": found.id,
        "type": found.type,
        "title": found.title,
        "username": found.username,
        "description": found.description,
        "members": members,
        "pinned": found.pinned_message.message_id if found.pinned_message else None,
    }


@router.get("/members/{user_id}")
async def chat_member(user_id: int, who: Chat, chat_id: int | None = None) -> dict:
    bot = await who.bot()
    target_chat = await who.target_chat(chat_id)
    try:
        member = await bot.get_chat_member(target_chat, user_id)
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"user_id": user_id, "status": member.status, "member": member.model_dump(mode="json")}


@router.post("/members/{user_id}/ban")
async def chat_ban(user_id: int, who: Chat, body: Moderation) -> dict:
    bot = await who.bot()
    chat_id = await who.target_chat(body.chat_id)
    await who.ensure_admin(chat_id)
    try:
        if body.undo:
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            return {"user_id": user_id, "banned": False}
        await bot.ban_chat_member(
            chat_id,
            user_id,
            until_date=_until(body.until),
            revoke_messages=body.revoke,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"user_id": user_id, "banned": True, "until": body.until}


@router.post("/members/{user_id}/mute")
async def chat_mute(user_id: int, who: Chat, body: Moderation) -> dict:
    from aiogram.types import ChatPermissions

    bot = await who.bot()
    allowed = ChatPermissions(
        can_send_messages=bool(body.undo),
        can_send_audios=bool(body.undo),
        can_send_documents=bool(body.undo),
        can_send_photos=bool(body.undo),
        can_send_videos=bool(body.undo),
        can_send_other_messages=bool(body.undo),
        can_add_web_page_previews=bool(body.undo),
    )
    chat_id = await who.target_chat(body.chat_id)
    await who.ensure_admin(chat_id)
    try:
        await bot.restrict_chat_member(
            chat_id, user_id, permissions=allowed, until_date=_until(body.until),
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"user_id": user_id, "muted": not body.undo, "until": body.until}


@router.post("/invites")
async def chat_invite(who: Chat, body: Invite) -> dict:
    bot = await who.bot()
    chat_id = await who.target_chat(body.chat_id)
    await who.ensure_admin(chat_id)
    try:
        link = await bot.create_chat_invite_link(
            chat_id,
            name=body.name,
            member_limit=body.member_limit,
            expire_date=_until(body.expires_in),
            creates_join_request=body.join_request,
        )
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {"url": link.invite_link, "name": link.name, "expires": link.expire_date}


@router.post("/albums")
async def album(body: Album, who: Chat) -> dict:
    if not 2 <= len(body.items) <= 10:
        raise HTTPException(400, "an album holds between two and ten files")
    bot = await who.bot()
    media = []
    total_size = 0
    for index, item in enumerate(body.items):
        try:
            data = base64.b64decode(item.data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, f"{item.name}: data is not base64") from None
        if not data:
            raise HTTPException(400, f"{item.name}: file is empty")
        if len(data) > MAX_FILE:
            raise HTTPException(413, f"{item.name}: {human_size(len(data))} is over the {human_size(MAX_FILE)} limit")
        total_size += len(data)
        if total_size > 50 * 1024 * 1024:
            raise HTTPException(413, f"album size {human_size(total_size)} is over the 50 MB limit")
        payload = BufferedInputFile(data, filename=item.name)
        caption = body.caption if index == 0 else None
        kind = item.media or "photo"
        if kind == "video":
            media.append(InputMediaVideo(media=payload, caption=caption))
        elif kind == "document":
            media.append(InputMediaDocument(media=payload, caption=caption))
        else:
            media.append(InputMediaPhoto(media=payload, caption=caption))
    chat_id = await who.target_chat(body.chat_id)
    try:
        sent = await bot.send_media_group(chat_id, media=media)
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


@router.get("/files/{file_id}")
async def download_file(file_id: str, who: Chat) -> dict:
    from io import BytesIO
    bot = await who.bot()
    try:
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            raise HTTPException(404, "file path not found")
        buffer = BytesIO()
        await bot.download_file(tg_file.file_path, destination=buffer)
        data = buffer.getvalue()
    except TelegramAPIError as refused:
        raise HTTPException(502, f"telegram refused: {refused}") from None
    return {
        "file_id": file_id,
        "file_path": tg_file.file_path,
        "size": len(data),
        "data": base64.b64encode(data).decode(),
    }
