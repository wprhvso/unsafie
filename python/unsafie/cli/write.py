import sys
from pathlib import Path
from typing import Any


def run(path: str, *, content: str | None = None) -> dict[str, Any]:
    if not path:
        return {"ok": False, "error": "path is required"}

    if content is None:
        content = sys.stdin.read()

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"failed to write {path}: {e}"}

    lines_count = len(content.splitlines())
    return {
        "ok": True,
        "path": str(target),
        "bytes": len(content.encode("utf-8")),
        "lines": lines_count,
    }
