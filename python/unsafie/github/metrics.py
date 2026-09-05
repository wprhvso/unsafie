"""Per-task counters of github traffic: how much was fetched and how much came from the cache.

`start()` is called at the beginning of a tool call; the counters live in a context variable,
so tasks spawned by asyncio.gather share the same dict and add to it.
"""

from contextvars import ContextVar

from unsafie.mime import human_size

_counters: ContextVar[dict[str, int] | None] = ContextVar("github_metrics", default=None)

LABELS = (
    ("requests", "{} request(s)"),
    ("hits", "{} cached"),
    ("bulk", "{} from a snapshot"),
)


def start() -> dict[str, int]:
    counters: dict[str, int] = {}
    _counters.set(counters)
    return counters


def bump(name: str, value: int = 1) -> None:
    counters = _counters.get()
    if counters is not None:
        counters[name] = counters.get(name, 0) + value


def summary(counters: dict[str, int] | None) -> str:
    if not counters:
        return ""
    parts = [template.format(counters[key]) for key, template in LABELS if counters.get(key)]
    if counters.get("bytes"):
        parts.append(human_size(counters["bytes"]))
    return ", ".join(parts)
