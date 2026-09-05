import html
import json
import logging
from pathlib import Path

from unsafie.settings import settings

logger = logging.getLogger(__name__)

PLACEHOLDER = "<!--PAYLOAD-->"
SCRIPT_ID = "payload"

FALLBACK = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>unsafie</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:16px/1.6 system-ui;margin:2rem auto;max-width:44rem;padding:0 1rem;color:#111;
background:#fff}pre{background:#f6f6f6;padding:.8rem;border-radius:6px;overflow-x:auto}
@media(prefers-color-scheme:dark){body{background:#111;color:#eee}pre{background:#1c1c1c}}</style>
<!--PAYLOAD-->
<div id="app"><pre id="raw"></pre></div>
<script>
const el = document.getElementById("payload");
const data = el ? JSON.parse(el.textContent) : null;
document.getElementById("raw").textContent = data ? data.content : "not found";
</script>
</html>"""

_cache: tuple[float, str] | None = None


def assets_dir() -> Path | None:
    """The immutable bundle directory, when the frontend has been built."""
    path = settings.static_dir / "_app"
    return path if path.is_dir() else None


def _index() -> str:
    global _cache
    path: Path = settings.static_dir / "index.html"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return FALLBACK
    if _cache is None or _cache[0] != mtime:
        _cache = (mtime, path.read_text(encoding="utf-8"))
        logger.info("static index.html loaded from %s", path)
    return _cache[1]


def render(payload: dict | None) -> str:
    page = _index()
    if payload is None:
        return page.replace(PLACEHOLDER, "")
    body = json.dumps(payload, ensure_ascii=False, default=str)
    tag = (
        f'<script id="{SCRIPT_ID}" type="application/json">'
        + body.replace("</", "<\\/")
        + "</script>"
    )
    if PLACEHOLDER in page:
        return page.replace(PLACEHOLDER, tag)
    logger.warning("index.html has no %s placeholder, injecting before </head>", PLACEHOLDER)
    if "</head>" in page:
        return page.replace("</head>", tag + "</head>", 1)
    return tag + page


def not_found(slug: str) -> str:
    return render({"error": "not_found", "slug": html.escape(slug)})
