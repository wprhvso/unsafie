import base64
import os
from pathlib import Path
from typing import Any

from unsafie_sdk.client import client, setting
from unsafie_sdk.errors import UnsafieError

MEDIA = ("document", "photo", "video", "audio", "voice", "animation", "sticker")


def _chat(chat_id: int | str | None) -> int | None:
    if chat_id is not None:
        return int(chat_id)
    found = setting("chat")
    return int(found) if found else None


def _turn() -> str | None:
    return os.environ.get("UNSAFIE_TURN") or None


def say(
    text: str,
    *,
    reply_to: int | None = None,
    buttons: Any = None,
    silent: bool = False,
    chat: int | str | None = None,
) -> dict:
    """Send a markdown message to the chat. Returns {"message_ids": [...]}."""
    import json

    body = {
        "text": text,
        "chat_id": _chat(chat),
        "reply_to": reply_to,
        "buttons": json.dumps(buttons, ensure_ascii=False) if buttons is not None else None,
        "silent": silent,
        "turn": _turn(),
    }
    return client().call("POST", "/chat/messages", body)


def file(
    path: str | Path | bytes,
    *,
    name: str | None = None,
    caption: str | None = None,
    kind: str = "document",
    silent: bool = False,
    chat: int | str | None = None,
) -> dict:
    """Send a file to the chat. Accepts a path or raw bytes; kind picks how Telegram shows it."""
    if isinstance(path, bytes):
        data = path
        filename = name or "file.bin"
    else:
        target = Path(path)
        if not target.is_file():
            raise UnsafieError(f"no file at {target}")
        data = target.read_bytes()
        filename = name or target.name
    if kind not in MEDIA:
        raise UnsafieError(f"kind must be one of {', '.join(MEDIA)}")
    body = {
        "name": filename,
        "data": base64.b64encode(data).decode(),
        "caption": caption,
        "media": kind,
        "silent": silent,
        "chat_id": _chat(chat),
        "turn": _turn(),
    }
    return client().call("POST", "/chat/files", body)


def photo(path: str | Path | bytes, *, caption: str | None = None, **kwargs) -> dict:
    """Send an image as a photo."""
    return file(path, caption=caption, kind="photo", **kwargs)


def edit(message_id: int, text: str, *, buttons: Any = None) -> dict:
    """Replace the text of a message the bot sent."""
    import json

    body = {
        "text": text,
        "buttons": json.dumps(buttons, ensure_ascii=False) if buttons is not None else None,
    }
    return client().call("POST", f"/chat/messages/{message_id}", body)


def delete(*message_ids: int) -> dict:
    """Delete messages by id."""
    last: dict = {}
    for message_id in message_ids:
        last = client().call("DELETE", f"/chat/messages/{message_id}")
    return last


def react(message_id: int, emoji: str = "👍", *, big: bool = False) -> dict:
    """Put a reaction on a message; an empty emoji removes it."""
    return client().call("POST", f"/chat/reactions/{message_id}", {"emoji": emoji, "big": big})


def pin(message_id: int, *, silent: bool = True) -> dict:
    """Pin a message."""
    return client().call("POST", f"/chat/pins/{message_id}", {"silent": silent, "unpin": False})


def note(text: str) -> None:
    """Write a line into the live log of this turn: the human sees it, the chat does not."""
    client().call("POST", "/chat/notes", {"text": text, "turn": _turn()})


def history(query: str | None = None, *, limit: int = 20, since: str | None = None, **kwargs):
    """Search this chat, or read the last messages when no query is given."""
    if query:
        params = {"query": query, "limit": limit, "since": since, **kwargs}
        return client().call("GET", "/chat/history/search", params=params).get("hits", [])
    return client().call("GET", "/chat/history", params={"limit": limit, **kwargs}).get("hits", [])


def info(chat: int | str | None = None) -> dict:
    """Type, title, description, member count and pinned message of the chat."""
    return client().call("GET", "/chat/info", params={"chat_id": _chat(chat)})
