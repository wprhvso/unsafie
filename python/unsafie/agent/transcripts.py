import gzip
import json
import logging
import uuid

from unsafie.database import SessionLocal
from unsafie.database.repositories.transcript import TranscriptRepository
from unsafie.mime import human_size
from unsafie.settings import settings

logger = logging.getLogger(__name__)


def encode(messages: list) -> bytes:
    return json.dumps(messages, ensure_ascii=False).encode()


def _types(message: dict) -> set[str]:
    content = message.get("content")
    if not isinstance(content, list):
        return set()
    return {block.get("type") for block in content if isinstance(block, dict)}


def _opens(message: dict) -> bool:
    return message.get("role") == "user" and "tool_result" not in _types(message)


def _dangling(message: dict) -> bool:
    if message.get("role") == "assistant":
        return bool({"tool_use", "server_tool_use"} & _types(message))
    return "tool_result" in _types(message)


def tidy(messages: list) -> list:
    kept = list(messages)
    while kept and _dangling(kept[-1]):
        kept.pop()
    return kept


def trim(messages: list, limit: int) -> list:
    sizes = [len(encode([message])) for message in messages]
    total = sum(sizes)
    start = 0
    while start < len(messages) and total > limit:
        total -= sizes[start]
        start += 1
    while start < len(messages) and not _opens(messages[start]):
        start += 1
    return messages[start:]


async def load(session_id: str) -> list | None:
    async with SessionLocal() as session:
        stored = await TranscriptRepository(session).get(session_id)
    if stored is None:
        return None
    try:
        messages = json.loads(gzip.decompress(stored.body))
    except (OSError, ValueError):
        logger.error("transcript %s cannot be read, starting over", session_id, exc_info=True)
        return None
    if not isinstance(messages, list):
        logger.error("transcript %s is not a message list, starting over", session_id)
        return None
    return messages


async def save(session_id: str, bot_id: int, chat_id: int, messages: list) -> int:
    kept = list(messages)
    raw = encode(kept)
    if len(raw) > settings.transcript_max_bytes:
        kept = trim(kept, settings.transcript_max_bytes)
        raw = encode(kept)
        logger.warning(
            "transcript %s was over %s, dropped the oldest %s message(s)",
            session_id,
            human_size(settings.transcript_max_bytes),
            len(messages) - len(kept),
        )
    async with SessionLocal() as session:
        await TranscriptRepository(session).save(
            session_id=session_id,
            bot_id=bot_id,
            chat_id=chat_id,
            body=gzip.compress(raw),
            lines=len(kept),
            raw_bytes=len(raw),
        )
    logger.info(
        "transcript %s stored: %s message(s), %s", session_id, len(kept), human_size(len(raw))
    )
    return len(kept)


async def fork(session_id: str, count: int, bot_id: int, chat_id: int) -> tuple[str, list] | None:
    messages = await load(session_id)
    if messages is None:
        return None
    kept = tidy(messages[: max(0, count)] if count else [])
    fresh = str(uuid.uuid4())
    await save(fresh, bot_id, chat_id, kept)
    logger.info(
        "transcript %s forked from %s at message %s of %s",
        fresh,
        session_id,
        len(kept),
        len(messages),
    )
    return fresh, kept
