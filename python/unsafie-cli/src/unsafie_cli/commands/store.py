import sys
import urllib.parse
from pathlib import Path

from unsafie_cli import api
from unsafie_cli.errors import NOT_FOUND, OK, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call


def _size(value: int) -> str:
    left = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if left < 1024 or unit == "GB":
            return f"{left:.0f}{unit}" if unit == "B" else f"{left:.1f}{unit}"
        left /= 1024
    return f"{left}B"


def blob_put(call: Call, out: Out) -> int:
    key = call.arg("key")
    source = call.arg("path")
    if source and source != "-":
        path = Path(source)
        if not path.is_file():
            raise CliError(f"no file at {path}", NOT_FOUND)
        data = path.read_bytes()
    else:
        data = sys.stdin.buffer.read()
    if not data:
        raise Usage("nothing to store", "unsafie blob put out/report.pdf report.pdf")
    answer = api.client(call).raw("PUT", f"/blobs/{urllib.parse.quote(key)}", data)
    out.send(answer, [f"stored {answer.get('key')} ({_size(int(answer.get('size') or 0))})"])
    return OK


def blob_get(call: Call, out: Out) -> int:
    key = call.arg("key")
    data = api.client(call).download(f"/blobs/{urllib.parse.quote(key)}")
    target = call.flag("out")
    if target:
        Path(target).write_bytes(data)
        out.send({"key": key, "path": target, "size": len(data)}, [f"wrote {target}"])
        return OK
    sys.stdout.buffer.write(data)
    return OK


def blob_ls(call: Call, out: Out) -> int:
    answer = api.client(call).call(
        "GET", "/blobs", params={"prefix": call.arg("prefix"), "limit": call.flag("limit", "50")}
    )
    if out.json_mode:
        out.send(answer)
        return OK
    rows = [
        [row["key"], _size(int(row["size"])), (row.get("machine") or "-")]
        for row in answer.get("blobs", [])
    ]
    if not rows:
        out.line("nothing stored")
        return OK
    out.table(rows, ["key", "size", "from"])
    out.line(out.dim(f"used {_size(int(answer.get('used') or 0))}"))
    return OK


def blob_rm(call: Call, out: Out) -> int:
    answer = api.client(call).call("DELETE", f"/blobs/{urllib.parse.quote(call.arg('key'))}")
    out.send(answer, ["deleted" if answer.get("deleted") else "there was no such key"])
    return OK


def blob_url(call: Call, out: Out) -> int:
    client = api.client(call)
    key = urllib.parse.quote(call.arg("key"))
    url = f"{client.base}/api/v1/blobs/{key}"
    out.send({"url": url, "note": "needs the Authorization header"}, [url])
    return OK


def kv_set(call: Call, out: Out) -> int:
    value = call.arg("value")
    if value == "-":
        value = sys.stdin.read()
    answer = api.client(call).call(
        "PUT", f"/kv/{urllib.parse.quote(call.arg('key'))}", {"value": value}
    )
    out.send(answer, [f"stored {answer.get('key')}"])
    return OK


def kv_get(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", f"/kv/{urllib.parse.quote(call.arg('key'))}")
    out.send(answer, [str(answer.get("value"))])
    return OK


def kv_ls(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/kv", params={"prefix": call.arg("prefix")})
    values = answer.get("values", {})
    if out.json_mode:
        out.send(answer)
        return OK
    if not values:
        out.line("nothing remembered")
        return OK
    out.table([[key, value[:60]] for key, value in values.items()], ["key", "value"])
    return OK


def kv_rm(call: Call, out: Out) -> int:
    answer = api.client(call).call("DELETE", f"/kv/{urllib.parse.quote(call.arg('key'))}")
    out.send(answer, ["deleted" if answer.get("deleted") else "there was no such key"])
    return OK


def secret_set(call: Call, out: Out) -> int:
    value = call.flag("value")
    if not value or call.on("from-stdin"):
        value = sys.stdin.read().strip()
    if not value:
        raise Usage("no value", "unsafie secret set OPENAI_KEY --from-stdin")
    answer = api.client(call).call(
        "PUT", f"/secrets/{urllib.parse.quote(call.arg('name'))}", {"value": value}
    )
    out.send(answer, [f"stored {answer.get('name')}"])
    return OK


def secret_get(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", f"/secrets/{urllib.parse.quote(call.arg('name'))}")
    out.send(answer, [str(answer.get("value"))])
    return OK


def secret_ls(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/secrets")
    if out.json_mode:
        out.send(answer)
        return OK
    rows = [[row["name"]] for row in answer.get("secrets", [])]
    if not rows:
        out.line("no secrets stored")
        return OK
    out.table(rows, ["name"])
    return OK


def secret_rm(call: Call, out: Out) -> int:
    answer = api.client(call).call("DELETE", f"/secrets/{urllib.parse.quote(call.arg('name'))}")
    out.send(answer, ["deleted" if answer.get("deleted") else "there was no such secret"])
    return OK


def secret_env(call: Call, out: Out) -> int:
    answer = api.client(call).call(
        "GET", "/secrets/values", params={"prefix": call.flag("prefix")}
    )
    values = answer.get("values", {})
    if out.json_mode:
        out.send(answer)
        return OK
    for name, value in values.items():
        out.line(f"export {name}={_quote(value)}")
    return OK


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
