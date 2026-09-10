import sys
from pathlib import Path
from typing import Any


def run(path: str, *, content: str | None = None) -> dict[str, Any]:
    if not path:
        return {"ok": False, "error": "path is required"}

    body = sys.stdin.read() if content is None else content
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"failed to write {path}: {e}"}

    lines_count = len(body.splitlines())
    return {
        "ok": True,
        "path": str(target),
        "bytes": len(body.encode("utf-8")),
        "lines": lines_count,
    }
