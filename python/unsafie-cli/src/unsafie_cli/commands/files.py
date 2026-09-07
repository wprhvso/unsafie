import subprocess
import sys
from pathlib import Path

from unsafie_cli.errors import FAILED, NOT_FOUND, OK, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

SKIP = {".git", "node_modules", "__pycache__", ".venv", "target", "dist", "build"}


def read(call: Call, out: Out) -> int:
    path = Path(call.arg("path"))
    if not path.is_file():
        raise CliError(f"no file at {path}", NOT_FOUND)
    try:
        body = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise CliError(f"{path} is not text", FAILED, "read it with cat or file") from None
    lines = body.splitlines()
    start, end = _range(call.flag("lines"), len(lines))
    width = len(str(end))
    shown = [f"{index + 1:>{width}}  {lines[index]}" for index in range(start - 1, end)]
    if out.json_mode:
        out.send({"path": str(path), "lines": len(lines), "from": start, "to": end, "text": "\n".join(shown)})
        return OK
    out.line(f"{path} [{len(lines)} lines]")
    out.line("\n".join(shown))
    return OK


def _range(spec: str, total: int) -> tuple[int, int]:
    if not spec:
        return 1, total
    head, _, tail = spec.partition(":")
    start = int(head) if head.isdigit() else 1
    end = int(tail) if tail.isdigit() else total
    return max(1, start), max(start, min(end, total))


def write(call: Call, out: Out) -> int:
    path = Path(call.arg("path"))
    body = sys.stdin.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    spool = path.with_name(path.name + ".unsafie.part")
    spool.write_text(body, encoding="utf-8")
    spool.replace(path)
    out.send({"path": str(path), "bytes": len(body.encode())}, [f"wrote {path} ({len(body)} chars)"])
    return OK


def patch(call: Call, out: Out) -> int:
    diff = sys.stdin.read()
    if not diff.strip():
        raise Usage("no diff on stdin", "unsafie fs patch < change.diff")
    target = call.arg("path")
    line = ["git", "apply", "--recount", "-"]
    if target:
        line = ["git", "apply", "--recount", "--include", target, "-"]
    done = subprocess.run(line, input=diff, text=True, check=False, capture_output=True)
    if done.returncode != 0:
        raise CliError(done.stderr.strip() or "the patch did not apply", FAILED)
    out.send({"applied": True}, ["patched"])
    return OK


def replace(call: Call, out: Out) -> int:
    path = Path(call.arg("path"))
    if not path.is_file():
        raise CliError(f"no file at {path}", NOT_FOUND)
    old = call.arg("old")
    new = call.arg("new")
    body = path.read_text(encoding="utf-8")
    found = body.count(old)
    if found == 0:
        raise CliError(f"'{old[:60]}' is not in {path}", NOT_FOUND)
    if found > 1 and not call.on("all"):
        raise CliError(
            f"'{old[:60]}' appears {found} times in {path}",
            FAILED,
            "make the fragment unique or pass --all",
        )
    path.write_text(body.replace(old, new), encoding="utf-8")
    out.send({"path": str(path), "replaced": found}, [f"replaced {found} in {path}"])
    return OK


def tree(call: Call, out: Out) -> int:
    root = Path(call.arg("dir") or ".")
    if not root.is_dir():
        raise CliError(f"no directory at {root}", NOT_FOUND)
    depth = int(call.flag("depth") or "2")
    rows: list[str] = []
    _walk(root, root, depth, rows)
    if out.json_mode:
        out.send({"root": str(root), "entries": rows})
        return OK
    out.line(f"{root}")
    out.line("\n".join(rows) if rows else "(empty)")
    return OK


def _walk(root: Path, here: Path, depth: int, rows: list[str]) -> None:
    if depth <= 0:
        return
    try:
        entries = sorted(here.iterdir(), key=lambda item: (item.is_file(), item.name))
    except PermissionError:
        return
    for entry in entries:
        if entry.name in SKIP or entry.name.startswith("."):
            continue
        relative = entry.relative_to(root)
        if entry.is_dir():
            rows.append(f"{relative}/")
            _walk(root, entry, depth - 1, rows)
        else:
            rows.append(f"{relative}  {entry.stat().st_size}")
