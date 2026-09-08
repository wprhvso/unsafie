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


def album(items: list[str | Path], *, caption: str | None = None, chat: int | str | None = None):
    """Send two to ten files as one message."""
    payload = []
    for item in items:
        target = Path(item)
        payload.append(
            {
                "name": target.name,
                "data": base64.b64encode(target.read_bytes()).decode(),
                "media": "photo" if target.suffix.lower() in (".jpg", ".jpeg", ".png") else "document",
            }
        )
    return client().call(
        "POST", "/chat/albums", {"items": payload, "caption": caption, "chat_id": _chat(chat)}
    )


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


def unpin(message_id: int | None = None) -> dict:
    """Unpin one message, or all of them when no id is given."""
    return client().call("POST", f"/chat/pins/{message_id or 0}", {"unpin": True})


def forward(message_id: int, to: int | str, *, copy: bool = False, caption: str | None = None):
    """Forward or copy a message into another chat."""
    return client().call(
        "POST",
        f"/chat/forwards/{message_id}",
        {"to_chat_id": int(to), "copy": copy, "caption": caption},
    )


def typing(action: str = "typing") -> dict:
    """Show a chat action for a few seconds."""
    return client().call("POST", "/chat/actions", {"action": action, "chat_id": _chat(None)})


def poll(question: str, options: list[str], **kwargs) -> dict:
    """Ask a poll: anonymous, multiple, quiz with correct=index, close_in='10m'."""
    body = {"question": question, "options": options, "chat_id": _chat(None), **kwargs}
    return client().call("POST", "/chat/polls", body)


def dice(emoji: str = "🎲") -> dict:
    """Throw a dice, dart, basketball, football, bowling or slot machine."""
    return client().call("POST", "/chat/dice", {"emoji": emoji, "chat_id": _chat(None)})


def location(latitude: float, longitude: float, **kwargs) -> dict:
    """Send a point on the map, or a venue with title and address."""
    body = {"latitude": latitude, "longitude": longitude, "chat_id": _chat(None), **kwargs}
    return client().call("POST", "/chat/locations", body)


def contact(phone: str, first_name: str, last_name: str | None = None) -> dict:
    """Send a contact card."""
    return client().call(
        "POST",
        "/chat/contacts",
        {"phone": phone, "first_name": first_name, "last_name": last_name, "chat_id": _chat(None)},
    )


def note(text: str) -> None:
    """Write a line into the live log of this turn: the human sees it, the chat does not."""
    client().call("POST", "/chat/notes", {"text": text, "turn": _turn()})


def progress(done: int, total: int, of: str = "") -> None:
    """Report progress into the live log."""
    note(f"{of + ': ' if of else ''}{done}/{total}")


def history(query: str | None = None, *, limit: int = 20, since: str | None = None, **kwargs):
    """Search this chat, or read the last messages when no query is given."""
    if query:
        params = {"query": query, "limit": limit, "since": since, **kwargs}
        return client().call("GET", "/chat/history/search", params=params).get("hits", [])
    return client().call("GET", "/chat/history", params={"limit": limit, **kwargs}).get("hits", [])


def info(chat: int | str | None = None) -> dict:
    """Type, title, description, member count and pinned message of the chat."""
    return client().call("GET", "/chat/info", params={"chat_id": _chat(chat)})


def member(user_id: int) -> dict:
    """Who a user is in this chat: status and rights."""
    return client().call("GET", f"/chat/members/{user_id}")


def ban(user_id: int, *, until: str | None = None, revoke: bool = False, undo: bool = False):
    """Ban or unban a member. Only at an explicit request of a chat administrator."""
    return client().call(
        "POST", f"/chat/members/{user_id}/ban", {"until": until, "revoke": revoke, "undo": undo}
    )


def mute(user_id: int, *, until: str | None = None, undo: bool = False) -> dict:
    """Mute or unmute a member. Only at an explicit request of a chat administrator."""
    return client().call("POST", f"/chat/members/{user_id}/mute", {"until": until, "undo": undo})


def invite(*, name: str | None = None, limit: int | None = None, expires: str | None = None):
    """Create an invite link to this chat."""
    return client().call(
        "POST", "/chat/invites", {"name": name, "member_limit": limit, "expires_in": expires}
    )
