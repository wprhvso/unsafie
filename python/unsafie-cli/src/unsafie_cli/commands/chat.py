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
