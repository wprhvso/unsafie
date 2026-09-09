import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

from unsafie.cli.client import client, setting
from unsafie_wire import markers

MEDIA = ("document", "photo", "video", "audio", "voice", "animation", "sticker")


def _chat(chat_id: int | str | None) -> int | None:
    if chat_id is not None:
        return int(chat_id)
    found = setting("chat")
    return int(found) if found else None


def _turn() -> str | None:
    return os.environ.get("UNSAFIE_TURN") or None


def send(
    text: str,
    *,
    reply_to: int | None = None,
    buttons: Any = None,
    silent: bool = False,
    chat: int | str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    body = {
        "text": text,
        "chat_id": _chat(chat),
        "reply_to": reply_to,
        "buttons": json.dumps(buttons, ensure_ascii=False) if buttons is not None else None,
        "silent": silent,
        "turn": _turn(),
        "idempotency_key": idempotency_key or os.environ.get("UNSAFIE_IDEMPOTENCY_KEY"),
    }
    res = client().call("POST", "/chat/messages", body)
    sys.stderr.write(markers.sent() + "\n")
    sys.stderr.flush()
    return res


def send_file(
    path: str | Path | bytes,
    *,
    name: str | None = None,
    caption: str | None = None,
    kind: str = "document",
    silent: bool = False,
    chat: int | str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if isinstance(path, bytes):
        data = path
        filename = name or "file.bin"
    else:
        target = Path(path)
        if not target.is_file():
            raise ValueError(f"no file at {target}")
        data = target.read_bytes()
        filename = name or target.name
    if kind not in MEDIA:
        raise ValueError(f"kind must be one of {', '.join(MEDIA)}")
    body = {
        "name": filename,
        "data": base64.b64encode(data).decode(),
        "caption": caption,
        "media": kind,
        "silent": silent,
        "chat_id": _chat(chat),
        "turn": _turn(),
        "idempotency_key": idempotency_key or os.environ.get("UNSAFIE_IDEMPOTENCY_KEY"),
    }
    res = client().call("POST", "/chat/files", body)
    sys.stderr.write(markers.sent() + "\n")
    sys.stderr.flush()
    return res


def send_photo(path: str | Path | bytes, *, caption: str | None = None, **kwargs) -> dict:
    return send_file(path, caption=caption, kind="photo", **kwargs)


def edit(message_id: int, text: str, *, buttons: Any = None) -> dict:
    body = {
        "text": text,
        "buttons": json.dumps(buttons, ensure_ascii=False) if buttons is not None else None,
    }
    return client().call("POST", f"/chat/messages/{message_id}", body)


def delete(*message_ids: int) -> dict:
    last: dict = {}
    for message_id in message_ids:
        last = client().call("DELETE", f"/chat/messages/{message_id}")
    return last or {"deleted": list(message_ids)}


def react(message_id: int, emoji: str = "👍", *, big: bool = False) -> dict:
    return client().call("POST", f"/chat/reactions/{message_id}", {"emoji": emoji, "big": big})


def pin(message_id: int, *, unpin: bool = False, silent: bool = False) -> dict:
    return client().call("POST", f"/chat/pins/{message_id}", {"silent": silent, "unpin": unpin})


def history(query: str | None = None, *, limit: int = 20, since: str | None = None, **kwargs) -> dict:
    if query:
        params = {"query": query, "limit": limit, "since": since, **kwargs}
        return client().call("GET", "/chat/history/search", params=params)
    return client().call("GET", "/chat/history", params={"limit": limit, **kwargs})


def info(chat: int | str | None = None) -> dict:
    return client().call("GET", "/chat/info", params={"chat_id": _chat(chat)})


def download(
    file_id: str,
    output: str | Path | None = None,
    *,
    chat: int | str | None = None,
) -> dict:
    res = client().call("GET", f"/chat/files/{file_id}", params={"chat_id": _chat(chat)})
    raw = base64.b64decode(res["data"])
    if output is not None:
        target = Path(output)
    else:
        name = Path(res.get("file_path") or file_id).name
        target = Path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {"file_id": file_id, "path": str(target), "bytes": len(raw)}
