import json
import logging
from datetime import UTC, datetime, timedelta

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    ChatPermissions,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputPollOption,
    MessageEntity,
    ReactionTypeEmoji,
    ReplyParameters,
)
from llmmd import process_markdown

from unsafie.agent.tools.base import ToolContext, current_turn, error, json_result, schema, text
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.repositories.response import ResponseRepository
from unsafie.scheduler.when import WhenError, duration
from unsafie.telegram import sender
from unsafie.telegram.keyboard import ButtonsError, parse_buttons
from unsafie.telegram.retry import download, retry

logger = logging.getLogger(__name__)

SERVER = "tg"
REACTIONS = (
    "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 "
    "🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 🤷‍♂ 🤷 🤷‍♀ 😡"
).split()
ACTIONS = (
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
)
DICE = ("🎲", "🎯", "🏀", "⚽", "🎳", "🎰")


def _tg(e: TelegramAPIError) -> dict:
    return error(f"Telegram refused: {e}")


def _reply(args: dict) -> ReplyParameters | None:
    if not args.get("reply_to"):
        return None
    return ReplyParameters(message_id=int(args["reply_to"]), allow_sending_without_reply=True)


def _caption(raw: str | None) -> tuple[str | None, list]:
    if not raw:
        return None, []
    chunks = process_markdown(raw)
    if not chunks:
        return None, []
    return chunks[0]["text"][:1024], [MessageEntity(**e) for e in chunks[0]["entities"]]


def _chat_ref(raw: str | None, default: int) -> int | str:
    raw = (raw or "").strip()
    if not raw:
        return default
    return int(raw) if raw.lstrip("-").isdigit() else raw


async def _after_send(ctx: ToolContext, msg, content: str, reply_to: int | None = None) -> dict:
    turn = await current_turn(ctx)
    await sender.record(
        bot_id=ctx.bot_id,
        chat_id=msg.chat.id,
        turn=turn,
        content=content,
        ids=[msg.message_id],
        reply_to=reply_to,
    )
    where = f" to chat {msg.chat.id}" if msg.chat.id != ctx.chat_id else ""
    return text(f"sent message_id={msg.message_id}{where}")


@register(
    SERVER,
    "set_reaction",
    "Put an emoji reaction on a message (mine or the user's): 👍 acknowledged, 👀 looking, ✍ working, "
    "🎉 done. Empty emoji removes the reaction. Standard Telegram emojis only. A reaction instead "
    "of a short 'ok' is cheaper and less noisy than a message.",
    schema(["message_id"], message_id=int, emoji=str, big=bool),
    replies=True,
)
async def set_reaction(ctx: ToolContext, args: dict) -> dict:
    emoji = (args.get("emoji") or "").strip()
    if emoji and emoji not in REACTIONS:
        return error("no such reaction; available: " + " ".join(REACTIONS))
    try:
        await retry(
            lambda: ctx.bot.set_message_reaction(
                ctx.chat_id,
                int(args["message_id"]),
                reaction=[ReactionTypeEmoji(emoji=emoji)] if emoji else [],
                is_big=bool(args.get("big")) or None,
            ),
            f"{ctx.prefix} reaction",
        )
    except TelegramAPIError as e:
        return _tg(e)
    return text(f"reaction {emoji or 'removed'} on {args['message_id']}")


@register(
    SERVER,
    "send_action",
    "Show a chat status ('typing…', 'sending a file…') for ~5 seconds: action = typing | "
    "upload_document | upload_photo | upload_video | record_voice | find_location …",
    schema([], action=str),
)
async def send_action(ctx: ToolContext, args: dict) -> dict:
    action = (args.get("action") or "typing").strip()
    if action not in ACTIONS:
        return error("action must be one of " + " | ".join(ACTIONS))
    try:
        await ctx.bot.send_chat_action(ctx.chat_id, action)
    except TelegramAPIError as e:
        return _tg(e)
    return text(f"action {action}")


@register(
    SERVER,
    "pin_message",
    "Pin a message (silent=true — without notifying everyone); unpin=true — unpin (without "
    "message_id — unpin all). In groups the bot needs pin rights.",
    schema([], message_id=int, unpin=bool, silent=bool),
)
async def pin_message(ctx: ToolContext, args: dict) -> dict:
    mid = args.get("message_id")
    try:
        if args.get("unpin"):
            if mid:
                await ctx.bot.unpin_chat_message(ctx.chat_id, int(mid))
                return text(f"unpinned {mid}")
            await ctx.bot.unpin_all_chat_messages(ctx.chat_id)
            return text("unpinned all")
        if not mid:
            return error("message_id is required")
        await ctx.bot.pin_chat_message(
            ctx.chat_id, int(mid), disable_notification=bool(args.get("silent"))
        )
    except TelegramAPIError as e:
        return _tg(e)
    return text(f"pinned {mid}")


@register(
    SERVER,
    "forward_message",
    "Forward message_id from the current chat to to_chat_id (a chat/channel id where the bot is a "
    "member; @username of a channel also works). copy=true — copy without the 'forwarded' mark "
    "(with a new caption if given). from_chat_id — forward from another chat.",
    schema(
        ["message_id", "to_chat_id"],
        message_id=int,
        to_chat_id=str,
        from_chat_id=str,
        copy=bool,
        caption=str,
        silent=bool,
    ),
    replies=True,
)
async def forward_message(ctx: ToolContext, args: dict) -> dict:
    to_chat = _chat_ref(args["to_chat_id"], ctx.chat_id)
    from_chat = _chat_ref(args.get("from_chat_id"), ctx.chat_id)
    mid = int(args["message_id"])
    try:
        if args.get("copy"):
            cap, ents = _caption(args.get("caption"))
            r = await ctx.bot.copy_message(
                to_chat,
                from_chat,
                mid,
                caption=cap,
                caption_entities=ents or None,
                disable_notification=bool(args.get("silent")) or None,
            )
            return text(f"copied as message_id={r.message_id} to {to_chat}")
        msg = await ctx.bot.forward_message(
            to_chat, from_chat, mid, disable_notification=bool(args.get("silent")) or None
        )
    except TelegramAPIError as e:
        return _tg(e)
    if msg.chat.id == ctx.chat_id:
        return await _after_send(ctx, msg, f"[forwarded {mid}]")
    return text(f"forwarded as message_id={msg.message_id} to {to_chat}")


@register(
    SERVER,
    "send_poll",
    "Poll: question, options — a JSON list of 2–10 strings. anonymous (default true), multiple — "
    "several answers, quiz=true with correct (0-based index) and explanation; close_in — auto-close "
    "after ('10m', 5s–10min). Telegram does not show polls in private chats, groups only.",
    schema(
        ["question", "options"],
        question=str,
        options=str,
        anonymous=bool,
        multiple=bool,
        quiz=bool,
        correct=int,
        explanation=str,
        close_in=str,
        silent=bool,
        reply_to=int,
    ),
    replies=True,
)
async def send_poll(ctx: ToolContext, args: dict) -> dict:
    try:
        options = json.loads(args["options"])
    except ValueError as e:
        return error(f"options is not JSON: {e}")
    if (
        not isinstance(options, list)
        or not 2 <= len(options) <= 10
        or not all(isinstance(o, str) and o.strip() for o in options)
    ):
        return error("options must be a JSON list of 2–10 non-empty strings")
    period = None
    if args.get("close_in"):
        try:
            period = max(5, min(duration(args["close_in"]), 600))
        except WhenError as e:
            return error(str(e))
    quiz = bool(args.get("quiz"))
    try:
        msg = await ctx.bot.send_poll(
            ctx.chat_id,
            args["question"][:300],
            [InputPollOption(text=o[:100]) for o in options],
            is_anonymous=args.get("anonymous", True),
            type="quiz" if quiz else "regular",
            allows_multiple_answers=bool(args.get("multiple")) and not quiz,
            correct_option_id=int(args["correct"])
            if quiz and args.get("correct") is not None
            else None,
            explanation=(args.get("explanation") or None) if quiz else None,
            open_period=period,
            disable_notification=bool(args.get("silent")) or None,
            reply_parameters=_reply(args),
        )
    except TelegramAPIError as e:
        return _tg(e)
    return await _after_send(
        ctx,
        msg,
        f"[poll] {args['question']}\n" + "\n".join(f"- {o}" for o in options),
        args.get("reply_to"),
    )


@register(
    SERVER,
    "stop_poll",
    "Close a poll by message_id and get the results.",
    schema(["message_id"], message_id=int),
)
async def stop_poll(ctx: ToolContext, args: dict) -> dict:
    try:
        poll = await ctx.bot.stop_poll(ctx.chat_id, int(args["message_id"]))
    except TelegramAPIError as e:
        return _tg(e)
    rows = [f"{o.text}: {o.voter_count}" for o in poll.options]
    return text(f"poll closed, {poll.total_voter_count} votes\n" + "\n".join(rows))


@register(
    SERVER,
    "send_location",
    "Send a point on the map: latitude, longitude; title + address — as a venue.",
    schema(
        ["latitude", "longitude"], latitude=str, longitude=str, title=str, address=str, reply_to=int
    ),
    replies=True,
)
async def send_location(ctx: ToolContext, args: dict) -> dict:
    try:
        lat = float(str(args["latitude"]).replace(",", "."))
        lon = float(str(args["longitude"]).replace(",", "."))
    except ValueError:
        return error("latitude/longitude must be numbers")
    try:
        if args.get("title"):
            msg = await ctx.bot.send_venue(
                ctx.chat_id,
                lat,
                lon,
                args["title"],
                args.get("address") or "",
                reply_parameters=_reply(args),
            )
        else:
            msg = await ctx.bot.send_location(ctx.chat_id, lat, lon, reply_parameters=_reply(args))
    except TelegramAPIError as e:
        return _tg(e)
    return await _after_send(
        ctx, msg, f"[location {lat},{lon}] {args.get('title') or ''}", args.get("reply_to")
    )


@register(
    SERVER,
    "send_contact",
    "Send a contact: phone, first_name, last_name.",
    schema(["phone", "first_name"], phone=str, first_name=str, last_name=str, reply_to=int),
    replies=True,
)
async def send_contact(ctx: ToolContext, args: dict) -> dict:
    try:
        msg = await ctx.bot.send_contact(
            ctx.chat_id,
            args["phone"],
            args["first_name"],
            last_name=args.get("last_name"),
            reply_parameters=_reply(args),
        )
    except TelegramAPIError as e:
        return _tg(e)
    return await _after_send(
        ctx, msg, f"[contact {args['first_name']} {args['phone']}]", args.get("reply_to")
    )


@register(
    SERVER,
    "send_dice",
    "Throw a dice/dart/basketball/football/bowling/slot: emoji from 🎲 🎯 🏀 ⚽ 🎳 🎰. Returns the value.",
    schema([], emoji=str, reply_to=int),
    replies=True,
)
async def send_dice(ctx: ToolContext, args: dict) -> dict:
    emoji = (args.get("emoji") or "🎲").strip()
    if emoji not in DICE:
        return error("emoji must be one of " + " ".join(DICE))
    try:
        msg = await ctx.bot.send_dice(ctx.chat_id, emoji=emoji, reply_parameters=_reply(args))
    except TelegramAPIError as e:
        return _tg(e)
    await _after_send(ctx, msg, f"[dice {emoji}]", args.get("reply_to"))
    return text(f"{emoji} = {msg.dice.value if msg.dice else '?'} (message_id={msg.message_id})")


@register(
    SERVER,
    "send_media_group",
    'Album of 2–10 files as one message: items — a JSON list of {"file_id": …} (received from '
    'Telegram) with optional "type": photo|video|document (default photo) and "caption". '
    "Types do not mix except photo+video.",
    schema(["items"], items=str, silent=bool, reply_to=int),
    replies=True,
)
async def send_media_group(ctx: ToolContext, args: dict) -> dict:
    try:
        items = json.loads(args["items"])
    except ValueError as e:
        return error(f"items is not JSON: {e}")
    if not isinstance(items, list) or not 2 <= len(items) <= 10:
        return error("items must be a list of 2–10 objects")
    media = []
    for it in items:
        if not isinstance(it, dict) or not it.get("file_id"):
            return error("each item must be an object with file_id")
        cap, ents = _caption(it.get("caption"))
        cls = {
            "photo": InputMediaPhoto,
            "video": InputMediaVideo,
            "document": InputMediaDocument,
        }.get((it.get("type") or "photo").lower())
        if cls is None:
            return error("type must be photo | video | document")
        media.append(cls(media=it["file_id"], caption=cap, caption_entities=ents or None))
    try:
        msgs = await ctx.bot.send_media_group(
            ctx.chat_id,
            media,
            disable_notification=bool(args.get("silent")) or None,
            reply_parameters=_reply(args),
        )
    except TelegramAPIError as e:
        return _tg(e)
    turn = await current_turn(ctx)
    ids = [m.message_id for m in msgs]
    await sender.record(
        bot_id=ctx.bot_id, chat_id=ctx.chat_id, turn=turn, content=f"[album x{len(ids)}]", ids=ids
    )
    return text(f"sent album ids={ids}")


@register(
    SERVER,
    "delete_messages",
    "Delete several messages at once: message_ids — comma-separated (up to 100). Same limits as delete_message.",
    schema(["message_ids"], message_ids=str),
)
async def delete_messages(ctx: ToolContext, args: dict) -> dict:
    ids = [
        int(x)
        for x in str(args["message_ids"]).replace(" ", "").split(",")
        if x.lstrip("-").isdigit()
    ]
    if not ids:
        return error("message_ids must be comma-separated numbers")
    try:
        ok = await ctx.bot.delete_messages(ctx.chat_id, ids[:100])
    except TelegramAPIError as e:
        return _tg(e)
    async with SessionLocal() as session:
        for mid in ids:
            await ResponseRepository(session).forget(ctx.bot_id, ctx.chat_id, mid)
    return text(f"deleted {len(ids)} messages" if ok else "Telegram returned false")


@register(
    SERVER,
    "chat_info",
    "Information about a chat (current by default): type, title, description, member count, "
    "pinned message, the bot's rights, administrators (in groups).",
    schema([], chat_id=str),
)
async def chat_info(ctx: ToolContext, args: dict) -> dict:
    chat_id = _chat_ref(args.get("chat_id"), ctx.chat_id)
    try:
        chat = await ctx.bot.get_chat(chat_id)
    except TelegramAPIError as e:
        return _tg(e)
    info: dict = {
        "id": chat.id,
        "type": chat.type,
        "title": chat.title,
        "username": chat.username,
        "name": chat.full_name if chat.type == "private" else None,
        "description": chat.description or chat.bio,
        "pinned_message_id": chat.pinned_message.message_id if chat.pinned_message else None,
        "is_forum": chat.is_forum,
    }
    if chat.type != "private":
        try:
            info["members"] = await ctx.bot.get_chat_member_count(chat.id)
            me = await ctx.bot.get_chat_member(chat.id, (await ctx.bot.me()).id)
            info["bot_status"] = me.status
            info["bot_can"] = {
                k: getattr(me, k, None)
                for k in (
                    "can_delete_messages",
                    "can_restrict_members",
                    "can_pin_messages",
                    "can_manage_chat",
                    "can_post_messages",
                )
                if getattr(me, k, None) is not None
            }
            admins = await ctx.bot.get_chat_administrators(chat.id)
            info["admins"] = [
                f"{a.user.full_name} (@{a.user.username}) [{a.status}]"
                if a.user.username
                else f"{a.user.full_name} [{a.status}]"
                for a in admins
            ]
        except TelegramAPIError as e:
            info["note"] = str(e)
    return json_result({k: v for k, v in info.items() if v is not None})


@register(
    SERVER,
    "chat_member",
    "Who user_id is in this chat: status (creator/administrator/member/restricted/left/kicked), rights, restriction expiry.",
    schema(["user_id"], user_id=int),
)
async def chat_member(ctx: ToolContext, args: dict) -> dict:
    try:
        m = await ctx.bot.get_chat_member(ctx.chat_id, int(args["user_id"]))
    except TelegramAPIError as e:
        return _tg(e)
    data = m.model_dump(exclude_none=True)
    data["user"] = {
        "id": m.user.id,
        "username": m.user.username,
        "name": m.user.full_name,
        "is_bot": m.user.is_bot,
    }
    return json_result(data)


@register(
    SERVER,
    "restrict_member",
    "Restrict a group member: mute=true — forbid writing (until — for how long: '1h', '1d'; empty — "
    "indefinitely), mute=false — lift restrictions. The bot needs admin rights. Only at an explicit "
    "request of a chat administrator.",
    schema(["user_id"], user_id=int, mute=bool, until=str),
)
async def restrict_member(ctx: ToolContext, args: dict) -> dict:
    mute = args.get("mute", True)
    until = None
    if args.get("until"):
        try:
            until = datetime.now(UTC) + timedelta(seconds=duration(args["until"]))
        except WhenError as e:
            return error(str(e))
    perms = ChatPermissions(
        can_send_messages=not mute,
        can_send_audios=not mute,
        can_send_documents=not mute,
        can_send_photos=not mute,
        can_send_videos=not mute,
        can_send_video_notes=not mute,
        can_send_voice_notes=not mute,
        can_send_polls=not mute,
        can_send_other_messages=not mute,
        can_add_web_page_previews=not mute,
        can_invite_users=True,
    )
    try:
        await ctx.bot.restrict_chat_member(
            ctx.chat_id, int(args["user_id"]), perms, until_date=until
        )
    except TelegramAPIError as e:
        return _tg(e)
    return text(
        f"user {args['user_id']} {'muted' if mute else 'unrestricted'}"
        + (f" until {until:%Y-%m-%d %H:%M}Z" if until else "")
    )


@register(
    SERVER,
    "ban_member",
    "Ban a group member (until — term: '7d'; empty — forever; revoke_messages=true — delete their "
    "messages) or unban (unban=true). Only at an explicit request of a chat administrator.",
    schema(["user_id"], user_id=int, unban=bool, until=str, revoke_messages=bool),
)
async def ban_member(ctx: ToolContext, args: dict) -> dict:
    uid = int(args["user_id"])
    try:
        if args.get("unban"):
            await ctx.bot.unban_chat_member(ctx.chat_id, uid, only_if_banned=True)
            return text(f"user {uid} unbanned")
        until = None
        if args.get("until"):
            until = datetime.now(UTC) + timedelta(seconds=duration(args["until"]))
        await ctx.bot.ban_chat_member(
            ctx.chat_id,
            uid,
            until_date=until,
            revoke_messages=bool(args.get("revoke_messages")) or None,
        )
    except WhenError as e:
        return error(str(e))
    except TelegramAPIError as e:
        return _tg(e)
    return text(f"user {uid} banned" + (f" until {until:%Y-%m-%d %H:%M}Z" if until else ""))


@register(
    SERVER,
    "chat_set",
    "Change a group/channel where the bot is admin: title, description; photo_file_id — avatar from a "
    "received photo. Only when explicitly asked.",
    schema([], title=str, description=str, photo_file_id=str),
)
async def chat_set(ctx: ToolContext, args: dict) -> dict:
    done = []
    try:
        if args.get("title"):
            await ctx.bot.set_chat_title(ctx.chat_id, args["title"][:128])
            done.append("title")
        if args.get("description") is not None:
            await ctx.bot.set_chat_description(ctx.chat_id, args["description"][:255] or None)
            done.append("description")
        if args.get("photo_file_id"):
            data = await download(ctx.bot, args["photo_file_id"], f"{ctx.prefix} download photo")
            await ctx.bot.set_chat_photo(ctx.chat_id, BufferedInputFile(data, filename="photo.jpg"))
            done.append("photo")
    except TelegramAPIError as e:
        return _tg(e)
    if not done:
        return error("nothing to change")
    return text("updated " + ", ".join(done))


@register(
    SERVER,
    "invite_link",
    "Invite link to a group/channel: a new one, optionally with member_limit and expires_in ('1d'); "
    "name — a label. The bot needs the invite right.",
    schema([], name=str, member_limit=int, expires_in=str, join_request=bool),
)
async def invite_link(ctx: ToolContext, args: dict) -> dict:
    expire = None
    if args.get("expires_in"):
        try:
            expire = datetime.now(UTC) + timedelta(seconds=duration(args["expires_in"]))
        except WhenError as e:
            return error(str(e))
    try:
        link = await ctx.bot.create_chat_invite_link(
            ctx.chat_id,
            name=args.get("name"),
            expire_date=expire,
            member_limit=int(args["member_limit"]) if args.get("member_limit") else None,
            creates_join_request=bool(args.get("join_request")) or None,
        )
    except TelegramAPIError as e:
        return _tg(e)
    return text(link.invite_link)


@register(
    SERVER,
    "edit_buttons",
    "Replace the buttons under message_id without editing the text. buttons='[]' removes them.",
    schema(["message_id", "buttons"], message_id=int, buttons=str),
    replies=True,
)
async def edit_buttons(ctx: ToolContext, args: dict) -> dict:
    try:
        markup = parse_buttons(args["buttons"])
    except ButtonsError as e:
        return error(str(e))
    try:
        await sender.edit(
            ctx.bot,
            bot_id=ctx.bot_id,
            chat_id=ctx.chat_id,
            message_id=int(args["message_id"]),
            markdown=None,
            reply_markup=markup,
        )
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return text("unchanged")
        return _tg(e)
    except TelegramAPIError as e:
        return _tg(e)
    return text("buttons updated")
