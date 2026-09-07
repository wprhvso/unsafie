import sys
from pathlib import Path

from unsafie_cli import api
from unsafie_cli.errors import NOT_FOUND, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call


def _content(reference: str) -> str:
    if reference == "-":
        body = sys.stdin.read()
    else:
        path = Path(reference)
        if not path.is_file():
            raise CliError(f"no file at {path}", NOT_FOUND, "pass a markdown file or `-` for stdin")
        body = path.read_text(encoding="utf-8")
    if not body.strip():
        raise Usage("the page is empty")
    return body


def create(call: Call, out: Out) -> int:
    body = {
        "content": _content(call.arg("file")),
        "title": call.flag("title") or None,
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/pages", body)
    out.send(answer, [answer["url"]])
    return 0


def listing(call: Call, out: Out) -> int:
    rows = api.client(call).call("GET", "/pages", params={"limit": call.flag("limit", "20")})
    if out.json_mode:
        out.send(rows)
        return 0
    out.table([(row["slug"], row.get("title") or "—", row["url"]) for row in rows])
    return 0


def update(call: Call, out: Out) -> int:
    body = {"content": _content(call.arg("file")), "title": call.flag("title") or None}
    answer = api.client(call).call("PUT", f"/pages/{call.arg('slug')}", body)
    out.send(answer, [answer["url"]])
    return 0


def remove(call: Call, out: Out) -> int:
    answer = api.client(call).call("DELETE", f"/pages/{call.arg('slug')}")
    out.send(answer, [f"deleted {call.arg('slug')}"])
    return 0
