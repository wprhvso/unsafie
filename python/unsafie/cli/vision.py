import glob
import sys
import time
from pathlib import Path
from typing import Any

from unsafie.cli import blobs
from unsafie.mime import image_problem, sniff_mime
from unsafie_wire import markers


def attach(
    paths: list[str],
    *,
    caption: str | None = None,
) -> dict[str, Any]:
    expanded: list[Path] = []
    for pattern in paths:
        matches = glob.glob(pattern)
        if matches:
            for match in sorted(matches):
                p = Path(match)
                if p.is_file():
                    expanded.append(p)
        else:
            p = Path(pattern)
            if p.is_file():
                expanded.append(p)
            else:
                return {"ok": False, "error": f"file not found: {pattern}"}

    if not expanded:
        return {"ok": False, "error": "no image files found"}

    attached: list[dict[str, Any]] = []
    now_ms = int(time.time() * 1000)

    for index, file_path in enumerate(expanded):
        data = file_path.read_bytes()
        mime = sniff_mime(data, file_path.name)
        problem = image_problem(data, mime)
        if problem:
            return {"ok": False, "error": f"{file_path.name}: {problem}"}

        ext = file_path.suffix or ".png"
        key = f"vision/{now_ms}_{index}{ext}"
        blobs.put(key, data)

        sys.stderr.write(markers.image(key, mime, caption) + "\n")
        sys.stderr.flush()

        attached.append(
            {
                "path": str(file_path),
                "bytes": len(data),
                "mime": mime,
                "key": key,
            },
        )

    return {
        "ok": True,
        "attached": attached,
        "count": len(attached),
    }
