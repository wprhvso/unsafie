import os
from pathlib import Path


def _client():
    from unsafie_sdk.client import client

    return client()


def create(content: str | Path, *, title: str | None = None) -> str:
    """Publish markdown as a web page and return its link. Accepts text or a path."""
    body = Path(content).read_text(encoding="utf-8") if isinstance(content, Path) else str(content)
    answer = _client().call(
        "POST",
        "/pages",
        {"content": body, "title": title, "turn": os.environ.get("UNSAFIE_TURN") or None},
    )
    return str(answer["url"])


def listing(limit: int = 20) -> list[dict]:
    """Pages published from this account."""
    return _client().call("GET", "/pages", params={"limit": limit}) or []


def update(slug: str, content: str | Path, *, title: str | None = None) -> str:
    """Replace the content of a page."""
    body = Path(content).read_text(encoding="utf-8") if isinstance(content, Path) else str(content)
    answer = _client().call("PUT", f"/pages/{slug}", {"content": body, "title": title})
    return str(answer["url"])


def delete(slug: str) -> dict:
    """Delete a page."""
    return _client().call("DELETE", f"/pages/{slug}")
