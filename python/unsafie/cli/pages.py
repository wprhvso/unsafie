import os
from pathlib import Path

from unsafie.cli.client import client


def _clean_slug(slug: str) -> str:
    return slug.rstrip("/").rsplit("/", 1)[-1].strip()


def create(content: str, *, title: str | None = None) -> dict:
    target = Path(content)
    body = target.read_text(encoding="utf-8") if target.is_file() else content
    return client().call(
        "POST",
        "/pages",
        {"content": body, "title": title, "turn": os.environ.get("UNSAFIE_TURN") or None},
    )


def read(slug: str, *, output: str | Path | None = None) -> dict:
    clean = _clean_slug(slug)
    data = client().call("GET", f"/pages/{clean}")
    if output and isinstance(data, dict) and "content" in data:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data["content"], encoding="utf-8")
        data["saved_to"] = str(target)
    return data


def update(slug: str, content: str, *, title: str | None = None) -> dict:
    clean = _clean_slug(slug)
    target = Path(content)
    body = target.read_text(encoding="utf-8") if target.is_file() else content
    return client().call("PUT", f"/pages/{clean}", {"content": body, "title": title})


def delete(slug: str) -> dict:
    clean = _clean_slug(slug)
    return client().call("DELETE", f"/pages/{clean}")
