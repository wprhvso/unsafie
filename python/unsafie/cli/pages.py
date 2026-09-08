import os
from pathlib import Path

from unsafie.cli.client import client


def create(content: str, *, title: str | None = None) -> dict:
    target = Path(content)
    body = target.read_text(encoding="utf-8") if target.is_file() else content
    return client().call(
        "POST",
        "/pages",
        {"content": body, "title": title, "turn": os.environ.get("UNSAFIE_TURN") or None},
    )


def listing(limit: int = 20) -> list[dict]:
    return client().call("GET", "/pages", params={"limit": limit}) or []


def update(slug: str, content: str, *, title: str | None = None) -> dict:
    target = Path(content)
    body = target.read_text(encoding="utf-8") if target.is_file() else content
    return client().call("PUT", f"/pages/{slug}", {"content": body, "title": title})


def delete(slug: str) -> dict:
    return client().call("DELETE", f"/pages/{slug}")
