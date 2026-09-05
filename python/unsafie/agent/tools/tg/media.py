import json
import logging

from aiogram.exceptions import TelegramAPIError

from unsafie.agent.tools.base import ToolContext, error, schema, text
from unsafie.agent.tools.registry import register
from unsafie.mime import (
    decode_text,
    human_size,
    image_problem,
    image_result,
    number_lines,
    sniff_mime,
)
from unsafie.telegram.retry import download, retry

logger = logging.getLogger(__name__)

SERVER = "tg"
READ_LIMIT = 5_000_000


@register(
    SERVER,
    "file_info",
    "Inspect a Telegram file by file_id without reading it fully: size, mime (by content), whether "
    "it is text or binary, number of lines. Use before read_document/view_photo for large or "
    "unclear files.",
    schema(["file_id"], file_id=str),
)
async def file_info(ctx: ToolContext, args: dict) -> dict:
    file_id = args["file_id"]
    try:
        meta = await retry(lambda: ctx.bot.get_file(file_id), f"{ctx.prefix} get_file {file_id}")
        data = await download(ctx.bot, file_id, f"{ctx.prefix} download {file_id}")
    except TelegramAPIError as e:
        return error(f"could not fetch the file: {e}")
    name = meta.file_path or ""
    mime = sniff_mime(data, name)
    info: dict = {
        "size": len(data),
        "size_human": human_size(len(data)),
        "mime": mime,
        "telegram_path": name,
    }
    decoded = decode_text(data)
    if decoded is not None:
        info["kind"] = "text"
        info["encoding"] = decoded[1]
        info["lines"] = len(decoded[0].splitlines())
        info["hint"] = "read_document"
    elif mime.startswith("image/"):
        info["kind"] = "image"
        info["hint"] = image_problem(data, mime) or "view_photo"
    else:
        info["kind"] = "binary"
        info["hint"] = (
            "cannot be read; can be stored to a repo via fs_download or a host via ssh_upload"
        )
    return text(json.dumps(info, ensure_ascii=False, indent=1))


@register(
    SERVER,
    "view_photo",
    "Download and look at an image from Telegram by file_id (from photo, sticker or document of an "
    "incoming message). jpeg/png/gif/webp up to 5 MB.",
    schema(["file_id"], file_id=str),
)
async def view_photo(ctx: ToolContext, args: dict) -> dict:
    file_id = args["file_id"]
    try:
        data = await download(ctx.bot, file_id, f"{ctx.prefix} download {file_id}")
    except TelegramAPIError as e:
        return error(f"could not download the file: {e}")
    mime = sniff_mime(data)
    problem = image_problem(data, mime)
    if problem:
        if mime in ("application/gzip", "video/webm"):
            problem = "animated stickers (tgs/webm) cannot be viewed"
        return error(f"cannot view: {problem}")
    return image_result(data, mime, f"{mime}, {human_size(len(data))}")


@register(
    SERVER,
    "read_document",
    "Download a text file from Telegram by file_id (document of an incoming message) and return its "
    "content with line numbers. Encoding is detected automatically (utf-8, utf-16, cp1251…). "
    "start_line/end_line — a range (1-based). Images: view_photo; binaries: file_info.",
    schema(["file_id"], file_id=str, start_line=int, end_line=int),
)
async def read_document(ctx: ToolContext, args: dict) -> dict:
    file_id = args["file_id"]
    try:
        data = await download(ctx.bot, file_id, f"{ctx.prefix} download {file_id}")
    except TelegramAPIError as e:
        return error(f"could not download the file: {e}")
    decoded = decode_text(data)
    if decoded is None:
        mime = sniff_mime(data)
        hint = " It is an image, use view_photo." if mime.startswith("image/") else ""
        return error(f"not a text file ({mime}, {human_size(len(data))}).{hint}")
    body, enc = decoded
    numbered, total = number_lines(body, args.get("start_line"), args.get("end_line"), READ_LIMIT)
    head = f"[{enc}, {total} lines]\n" if enc != "utf-8" else ""
    return text(head + (numbered or "<empty file>"))
