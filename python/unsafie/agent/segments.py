import gzip
import json
from unsafie.log import get_logger
from dataclasses import dataclass

from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.segment import SegmentRepository
from unsafie.mime import human_size
from unsafie.settings import settings

logger = get_logger(__name__)


@dataclass(frozen=True)
class History:
    messages: list
    system: str | None
    lost: bool


def encode(messages: list) -> bytes:
    return json.dumps(messages, ensure_ascii=False).encode()


def tidy(messages: list) -> list:
    kept = list(messages)
    while kept and kept[-1].get("role") != "assistant":
        kept.pop()
    return kept


def normalize(segment: list) -> list:
    kept = tidy(segment)
    if not any(message.get("role") == "assistant" for message in kept):
        return []
    deduped = []
    prev_key = None
    for m in kept:
        key = json.dumps(m, sort_keys=True)
        if key == prev_key:
            continue
        prev_key = key
        deduped.append(m)
    return deduped


def _decode(body: bytes) -> list:
    try:
        messages = json.loads(gzip.decompress(body))
    except (OSError, ValueError):
        logger.exception("a history segment is unreadable, skipping it")
        return []
    return messages if isinstance(messages, list) else []


async def load(turn: Turn) -> History:
    if turn.parent_id is None:
        return History([], None, False)
    async with SessionLocal() as session:
        found = await SegmentRepository(session).lineage(
            turn.parent_id,
            max_depth=settings.lineage_depth,
            budget=settings.history_max_bytes,
        )
    messages: list = []
    prev_key = None
    for body in found.bodies:
        for m in _decode(body):
            key = json.dumps(m, sort_keys=True)
            if key == prev_key:
                continue
            prev_key = key
            messages.append(m)
    logger.info(
        "turn=%s resumed %s message(s) from %s segment(s), %s",
        turn.id,
        len(messages),
        found.segments,
        human_size(found.bytes),
    )
    return History(messages, found.system, not messages)


async def save(turn: Turn, segment: list, system: str | None) -> int:
    kept = normalize(segment)
    if not kept:
        logger.info("turn=%s produced no reply, nothing stored", turn.id)
        return 0
    raw = encode(kept)
    async with SessionLocal() as session:
        await SegmentRepository(session).save(
            turn.id, body=gzip.compress(raw), count=len(kept), size=len(raw), system=system,
        )
    logger.info(
        "turn=%s stored %s message(s), %s%s",
        turn.id,
        len(kept),
        human_size(len(raw)),
        " with a system snapshot" if system else "",
    )
    return len(kept)
