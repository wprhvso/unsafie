import base64
import sys
from pathlib import Path

from unsafie_cli import api
from unsafie_cli.errors import NOT_FOUND, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call
from unsafie_wire import markers

MEDIA = ("document", "photo", "video", "audio", "voice", "animation", "sticker")


def _text_of(call: Call, name: str) -> str:
    value = call.arg(name)
    if value == "-":
        value = sys.stdin.read()
    if not value.strip():
        raise Usage("nothing to send", "pass the text as an argument or `-` to read stdin")
    return value


def say(call: Call, out: Out) -> int:
    body = {
        "text": _text_of(call, "text"),
        "chat_id": api.chat_of(call),
        "reply_to": int(call.flag("reply-to")) if call.flag("reply-to") else None,
        "buttons": call.flag("buttons") or None,
        "silent": call.on("silent"),
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/chat/messages", body)
    ids = answer.get("message_ids", [])
    out.line(markers.emit(markers.BlockKind.SENT, message_ids=ids))
    out.send(answer, [f"sent {' '.join(str(i) for i in ids)}"])
    return 0


def file(call: Call, out: Out) -> int:
    path = Path(call.arg("path"))
    if not path.is_file():
        raise CliError(f"no file at {path}", NOT_FOUND)
    media = (call.flag("kind") or "document").lower()
    if media not in MEDIA:
        raise Usage(f"kind must be one of {', '.join(MEDIA)}")
    body = {
        "name": path.name,
        "data": base64.b64encode(path.read_bytes()).decode(),
        "caption": call.flag("caption") or None,
        "media": media,
        "chat_id": api.chat_of(call),
        "silent": call.on("silent"),
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/chat/files", body)
    out.line(markers.emit(markers.BlockKind.SENT, message_ids=answer.get("message_ids") or []))
    out.send(answer, [f"sent {answer.get('sent_as')} {path.name} ({answer.get('bytes')} bytes)"])
    return 0


def edit(call: Call, out: Out) -> int:
    body = {
        "text": call.arg("text") or None,
        "buttons": call.flag("buttons") or None,
        "chat_id": api.chat_of(call),
    }
    message_id = call.arg("id")
    answer = api.client(call).call("POST", f"/chat/messages/{message_id}", body)
    out.send(answer, [f"edited {answer.get('edited')} of {message_id}"])
    return 0


def remove(call: Call, out: Out) -> int:
    client = api.client(call)
    chat_id = api.chat_of(call)
    gone: list[str] = []
    for message_id in call.many("id"):
        client.call("DELETE", f"/chat/messages/{message_id}", params={"chat_id": chat_id})
        gone.append(message_id)
    out.send({"deleted": gone}, [f"deleted {' '.join(gone)}"])
    return 0


def note(call: Call, out: Out) -> int:
    body = {"text": _text_of(call, "text"), "turn": api.turn_of()}
    answer = api.client(call).call("POST", "/chat/notes", body)
    out.send(answer, ["noted"])
    return 0


def progress(call: Call, out: Out) -> int:
    value = call.arg("value")
    of = call.flag("of")
    body = {"text": f"{of}: {value}" if of else value, "turn": api.turn_of()}
    answer = api.client(call).call("POST", "/chat/notes", body)
    out.send(answer, [f"progress {value}"])
    return 0


def typing(call: Call, out: Out) -> int:
    body = {"action": call.arg("action") or "typing", "chat_id": api.chat_of(call)}
    answer = api.client(call).call("POST", "/chat/actions", body)
    out.send(answer, [f"{body['action']}…"])
    return 0


def react(call: Call, out: Out) -> int:
    body = {
        "emoji": call.arg("emoji"),
        "big": call.on("big"),
        "chat_id": api.chat_of(call),
    }
    answer = api.client(call).call("POST", f"/chat/reactions/{call.arg('id')}", body)
    out.send(answer, [f"reaction {answer.get('emoji') or 'removed'} on {answer.get('message_id')}"])
    return 0


def pin(call: Call, out: Out) -> int:
    body = {"silent": call.on("silent"), "chat_id": api.chat_of(call)}
    answer = api.client(call).call("POST", f"/chat/pins/{call.arg('id')}", body)
    out.send(answer, [f"pinned {answer.get('message_id')}"])
    return 0


def unpin(call: Call, out: Out) -> int:
    body = {"unpin": True, "chat_id": api.chat_of(call)}
    answer = api.client(call).call("POST", f"/chat/pins/{call.arg('id') or 0}", body)
    out.send(answer, ["unpinned"])
    return 0


def forward(call: Call, out: Out) -> int:
    target = call.flag("to")
    if not target:
        raise Usage("no destination", "unsafie forward 1421 --to @channel")
    body = {
        "to": target,
        "copy": call.on("copy"),
        "caption": call.flag("caption") or None,
        "from_chat_id": api.chat_of(call),
    }
    answer = api.client(call).call("POST", f"/chat/forwards/{call.arg('id')}", body)
    out.send(answer, [f"sent to {answer.get('chat_id')}"])
    return 0


def poll(call: Call, out: Out) -> int:
    options = call.many("option") if call.args.get("option") else []
    if not options:
        options = [piece for piece in (call.flags.get("option") or "").split("|") if piece]
    body = {
        "question": call.arg("question"),
        "options": options,
        "multiple": call.on("multiple"),
        "quiz": call.on("quiz"),
        "correct": int(call.flag("correct")) if call.flag("correct") else None,
        "close_in": _seconds(call.flag("close-in")),
        "chat_id": api.chat_of(call),
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/chat/polls", body)
    out.line(markers.emit(markers.BlockKind.SENT, message_ids=answer.get("message_ids") or []))
    out.send(answer, [f"poll sent {answer.get('message_ids')}"])
    return 0


def dice(call: Call, out: Out) -> int:
    body = {"emoji": call.arg("emoji") or "🎲", "chat_id": api.chat_of(call), "turn": api.turn_of()}
    answer = api.client(call).call("POST", "/chat/dice", body)
    out.line(markers.emit(markers.BlockKind.SENT, message_ids=answer.get("message_ids") or []))
    out.send(answer, [f"{body['emoji']} = {answer.get('value')}"])
    return 0


def location(call: Call, out: Out) -> int:
    body = {
        "latitude": float(call.arg("lat")),
        "longitude": float(call.arg("lon")),
        "title": call.flag("title") or None,
        "address": call.flag("address") or None,
        "chat_id": api.chat_of(call),
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/chat/locations", body)
    out.line(markers.emit(markers.BlockKind.SENT, message_ids=answer.get("message_ids") or []))
    out.send(answer, ["sent"])
    return 0


def contact(call: Call, out: Out) -> int:
    body = {
        "phone": call.arg("phone"),
        "first_name": call.arg("name"),
        "last_name": call.flag("last") or None,
        "chat_id": api.chat_of(call),
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/chat/contacts", body)
    out.line(markers.emit(markers.BlockKind.SENT, message_ids=answer.get("message_ids") or []))
    out.send(answer, ["sent"])
    return 0


def album(call: Call, out: Out) -> int:
    items = []
    for name in call.many("path"):
        path = Path(name)
        if not path.is_file():
            raise CliError(f"no file at {path}", NOT_FOUND)
        items.append(
            {
                "name": path.name,
                "data": base64.b64encode(path.read_bytes()).decode(),
                "media": "photo" if path.suffix.lower() in (".jpg", ".jpeg", ".png") else "document",
            }
        )
    body = {
        "items": items,
        "caption": call.flag("caption") or None,
        "chat_id": api.chat_of(call),
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/chat/albums", body)
    out.line(markers.emit(markers.BlockKind.SENT, message_ids=answer.get("message_ids") or []))
    out.send(answer, [f"sent {len(items)} files"])
    return 0


def _seconds(value: str) -> int | None:
    if not value:
        return None
    units = {"s": 1, "m": 60, "h": 3600}
    if value[-1] in units and value[:-1].isdigit():
        return int(value[:-1]) * units[value[-1]]
    return int(value) if value.isdigit() else None
