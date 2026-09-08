import time

from unsafie_cli import api
from unsafie_cli.errors import OK, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _since(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip().lower()
    if text[-1] in UNITS and text[:-1].replace(".", "", 1).isdigit():
        return int(time.time() - float(text[:-1]) * UNITS[text[-1]])
    if text.isdigit():
        return int(text)
    raise Usage(f"'{value}' is neither an age nor a timestamp", "use 7d, 12h or a unix time")


def _rows(hits: list[dict]) -> list[list[str]]:
    return [
        [
            str(hit.get("message_id") or "—"),
            hit.get("at", ""),
            (hit.get("name") or hit.get("who") or "")[:16],
            (hit.get("text") or "").replace("\n", " ")[:70],
        ]
        for hit in hits
    ]


def search(call: Call, out: Out) -> int:
    params = {
        "query": call.arg("query"),
        "kind": call.flag("who") or "any",
        "since": _since(call.flag("since")),
        "limit": call.flag("limit", "20"),
    }
    answer = api.client(call).call("GET", "/chat/history/search", params=params)
    if out.json_mode:
        out.send(answer)
        return OK
    hits = answer.get("hits", [])
    if not hits:
        out.line("nothing found")
        return OK
    out.table(_rows(hits), ["id", "when", "who", "text"])
    return OK


def get(call: Call, out: Out) -> int:
    params = {
        "message_id": call.flag("id") or None,
        "around": call.flag("around", "5"),
        "limit": call.flag("limit", "20"),
    }
    answer = api.client(call).call("GET", "/chat/history", params=params)
    if out.json_mode:
        out.send(answer)
        return OK
    hits = answer.get("hits", [])
    if not hits:
        out.line("this chat has no history yet")
        return OK
    for hit in hits:
        head = f"[{hit.get('message_id')}] {hit.get('at')} {hit.get('name') or hit.get('who')}"
        out.line(out.bold(head))
        out.line((hit.get("text") or "").rstrip())
    return OK


def info(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/chat/info", params={"chat_id": call.flag("id") or None})
    out.send(
        answer,
        [
            f"{answer.get('title') or answer.get('username') or answer['id']} · {answer['type']}",
            f"members: {answer.get('members')}",
            f"pinned: {answer.get('pinned') or '—'}",
        ],
    )
    return OK


def member(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", f"/chat/members/{call.arg('user')}")
    out.send(answer, [f"{answer['user_id']}: {answer['status']}"])
    return OK


def ban(call: Call, out: Out) -> int:
    body = {"until": call.flag("until") or None, "revoke": call.on("revoke"), "undo": call.on("unban")}
    answer = api.client(call).call("POST", f"/chat/members/{call.arg('user')}/ban", body)
    out.send(answer, [f"{answer['user_id']}: {'banned' if answer['banned'] else 'unbanned'}"])
    return OK


def mute(call: Call, out: Out) -> int:
    body = {"until": call.flag("until") or None, "undo": call.on("unmute")}
    answer = api.client(call).call("POST", f"/chat/members/{call.arg('user')}/mute", body)
    out.send(answer, [f"{answer['user_id']}: {'muted' if answer['muted'] else 'unmuted'}"])
    return OK


def invite(call: Call, out: Out) -> int:
    body = {
        "name": call.flag("name") or None,
        "member_limit": int(call.flag("limit")) if call.flag("limit") else None,
        "expires_in": call.flag("expires") or None,
    }
    answer = api.client(call).call("POST", "/chat/invites", body)
    out.send(answer, [answer["url"]])
    return OK
