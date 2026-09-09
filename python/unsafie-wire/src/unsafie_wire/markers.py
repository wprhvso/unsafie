import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

MARKER = "::unsafie::"


class BlockKind(StrEnum):
    IMAGE = "image"
    FILE = "file"
    NOTE = "note"
    LINK = "link"
    SENT = "sent"
    RESULT = "result"
    PROGRESS = "progress"
    ERROR = "error"
    STOP = "stop"
    LLM_START = "llm.start"
    LLM_THOUGHT = "llm.thought"
    LLM_DELTA = "llm.delta"
    LLM_END = "llm.end"


@dataclass(frozen=True, slots=True)
class Block:
    kind: BlockKind
    data: dict[str, Any]


def emit(kind: BlockKind | str, **fields: Any) -> str:
    payload: dict[str, Any] = {"kind": str(BlockKind(kind))}
    payload.update({k: v for k, v in fields.items() if v is not None})
    return MARKER + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_line(line: str) -> Block | None:
    text = line.strip()
    if not text.startswith(MARKER):
        return None
    try:
        payload = json.loads(text[len(MARKER) :])
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        kind = BlockKind(payload.pop("kind", ""))
    except ValueError:
        return None
    return Block(kind, payload)


def split(text: str) -> tuple[str, list[Block]]:
    kept: list[str] = []
    blocks: list[Block] = []
    for line in text.splitlines():
        block = parse_line(line)
        if block is None:
            kept.append(line)
        else:
            blocks.append(block)
    return "\n".join(kept), blocks


def image(blob: str, mime: str = "image/png", caption: str | None = None) -> str:
    return emit(BlockKind.IMAGE, blob=blob, mime=mime, caption=caption)


def file(blob: str, name: str, caption: str | None = None) -> str:
    return emit(BlockKind.FILE, blob=blob, name=name, caption=caption)


def note(text: str) -> str:
    return emit(BlockKind.NOTE, text=text)


def link(url: str, title: str | None = None) -> str:
    return emit(BlockKind.LINK, url=url, title=title)


def result(value: Any) -> str:
    return emit(BlockKind.RESULT, value=value)


def sent() -> str:
    return emit(BlockKind.SENT)


def stop(message: str | None = None) -> str:
    return emit(BlockKind.STOP, message=message)


def llm_start(id: str, model: str) -> str:
    return emit(BlockKind.LLM_START, id=id, model=model)


def llm_thought(id: str, text: str) -> str:
    return emit(BlockKind.LLM_THOUGHT, id=id, text=text)


def llm_delta(id: str, text: str) -> str:
    return emit(BlockKind.LLM_DELTA, id=id, text=text)


def llm_end(id: str, usage: dict[str, Any] | None = None) -> str:
    return emit(BlockKind.LLM_END, id=id, usage=usage)
