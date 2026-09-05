import base64
import logging
import time

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from llmmd import process_markdown

from unsafie.agent.tools.base import ToolContext, current_turn, error, schema, text
from unsafie.agent.tools.files import deliver
from unsafie.agent.tools.registry import register
from unsafie.database.models.response import ResponseKind
from unsafie.log import short
from unsafie.telegram import sender
from unsafie.telegram.keyboard import ButtonsError, describe, parse_buttons
from unsafie.telegram.retry import download

logger = logging.getLogger(__name__)

SERVER = "tg"

BUTTONS_HELP = (
    "buttons — inline keyboard under the message as JSON: a list of rows, a row is a list of buttons; "
    'a button is a string (text = data) or {"text": …, "data": …} / {"text": …, "url": …}. '
    '["Yes","No"] — two buttons stacked, [["Yes","No"]] — in one row. data up to 64 bytes. '
    "A press comes back to you as a message with a callback field."
)


@register(
    SERVER,
    "send_message",
    "Send a message to the current chat. Markdown text; long text is split into several messages "
    "automatically. reply_to — reply to a specific message_id explicitly (decided automatically "
    "otherwise); silent=true — no notification sound. " + BUTTONS_HELP,
    schema(["text"], text=str, buttons=str, reply_to=int, silent=bool),
    replies=True,
)
async def send_message(ctx: ToolContext, args: dict) -> dict:
    started = time.perf_counter()
    value = args["text"]
    logger.debug("%s send_message markdown=%s", ctx.prefix, short(value))
    chunks = process_markdown(value)
    if not chunks:
        return error("the text is empty")
    try:
        markup = parse_buttons(args.get("buttons"))
    except ButtonsError as e:
        return error(str(e))
    turn = await current_turn(ctx)
    try:
        response = await sender.send(
            ctx.bot,
            bot_id=ctx.bot_id,
            chat_id=ctx.chat_id,
            markdown=value,
            kind=ResponseKind.AGENT,
            turn=turn,
            reply_to=args.get("reply_to"),
            reply_markup=markup,
            silent=bool(args.get("silent")),
        )
    except TelegramAPIError as e:
        logger.error("%s send_message failed error=%s", ctx.prefix, e)
        return error(f"Telegram rejected the message: {e}")
    logger.info(
        "%s send_message done messages=%s reply_to=%s in %.1fms",
        ctx.prefix,
        response.message_ids,
        response.reply_to,
        (time.perf_counter() - started) * 1000,
    )
    note = f" as reply to {response.reply_to}" if response.reply_to else ""
    if markup is not None and markup.inline_keyboard:
        note += f" buttons: {describe(markup)}"
    return text(f"sent {len(response.message_ids)} message(s) ids={response.message_ids}{note}")


@register(
    SERVER,
    "send_file",
    "Send a file to the current chat. Exactly one source: content (text; base64=true for a binary "
    "encoded in base64) or file_id (re-send a file received in Telegram). filename is required. "
    "caption — markdown (a long one goes as a separate message). kind — how to show it: document "
    "(default) | photo | video | audio | voice (ogg/opus) | animation (gif/mp4) | sticker (webp); "
    "as_photo=true is the same as kind=photo. silent=true — no notification sound. " + BUTTONS_HELP,
    schema(
        ["filename"],
        filename=str,
        content=str,
        base64=bool,
        file_id=str,
        caption=str,
        kind=str,
        as_photo=bool,
        buttons=str,
        silent=bool,
    ),
    replies=True,
)
async def send_file(ctx: ToolContext, args: dict) -> dict:
    content, file_id = args.get("content"), args.get("file_id")
    if (content is None) == (not file_id):
        return error("exactly one source is required: content or file_id")
    if file_id:
        try:
            data = await download(ctx.bot, file_id, f"{ctx.prefix} download {file_id}")
        except TelegramAPIError as e:
            return error(f"could not download the file from Telegram: {e}")
    elif args.get("base64"):
        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as e:
            return error(f"content is not base64: {e}")
    else:
        data = content.encode()
    return await deliver(
        ctx,
        data,
        args["filename"],
        caption=args.get("caption"),
        as_photo=bool(args.get("as_photo")),
        kind=args.get("kind"),
        buttons=args.get("buttons"),
        silent=bool(args.get("silent")),
    )


@register(
    SERVER,
    "edit_message",
    "Edit your own message by message_id: text — new markdown (or caption for a file; must fit into "
    "one message), buttons — new buttons. Editing text removes old buttons unless passed again; "
    "buttons='[]' without text removes them. Useful for progress of long tasks and for removing "
    "buttons after a press. Other people's messages cannot be edited.",
    schema(["message_id"], message_id=int, text=str, buttons=str),
    replies=True,
)
async def edit_message(ctx: ToolContext, args: dict) -> dict:
    message_id = int(args["message_id"])
    value = args.get("text")
    raw_buttons = args.get("buttons")
    if value is None and raw_buttons is None:
        return error("text and/or buttons is required")
    if value is not None and not process_markdown(value):
        return error("the text is empty")
    try:
        markup = parse_buttons(raw_buttons)
    except ButtonsError as e:
        return error(str(e))
    try:
        what = await sender.edit(
            ctx.bot,
            bot_id=ctx.bot_id,
            chat_id=ctx.chat_id,
            message_id=message_id,
            markdown=value,
            reply_markup=markup,
        )
    except ValueError as e:
        return error(str(e))
    except TelegramBadRequest as e:
        msg = str(e)
        if "not modified" in msg:
            return text(f"message {message_id}: unchanged")
        if "can't be edited" in msg or "message to edit not found" in msg:
            return error(
                f"message {message_id} cannot be edited: not mine, deleted or too old ({e})"
            )
        return error(f"Telegram refused: {e}")
    except TelegramAPIError as e:
        return error(f"Telegram refused: {e}")
    note = f" buttons: {describe(markup)}" if markup is not None and markup.inline_keyboard else ""
    if markup is not None and not markup.inline_keyboard:
        note = " buttons removed"
    return text(f"edited {what} of message {message_id}{note}")


@register(
    SERVER,
    "delete_message",
    "Delete a chat message by message_id — mine or the user's (in private chats not older than 48h; "
    "in groups the bot needs admin rights to delete others' messages). Delete other people's "
    "messages only when explicitly asked.",
    schema(["message_id"], message_id=int),
)
async def delete_message(ctx: ToolContext, args: dict) -> dict:
    message_id = int(args["message_id"])
    try:
        await sender.delete(ctx.bot, bot_id=ctx.bot_id, chat_id=ctx.chat_id, message_id=message_id)
    except TelegramBadRequest as e:
        return error(
            f"could not delete {message_id}: {e}. The message may not exist, be older than 48 hours, "
            "or the bot lacks rights to delete others' messages in this group."
        )
    except TelegramAPIError as e:
        return error(f"Telegram refused: {e}")
    return text(f"deleted message {message_id}")
