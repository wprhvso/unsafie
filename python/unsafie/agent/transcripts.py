import gzip
import json
import logging
import uuid
from pathlib import Path

from unsafie.agent.options import transcript_path
from unsafie.database import SessionLocal
from unsafie.database.repositories.transcript import TranscriptRepository
from unsafie.mime import human_size
from unsafie.settings import settings

logger = logging.getLogger(__name__)

SESSION_FIELD = "sessionId"


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("transcript %s cannot be read", path, exc_info=True)
        return None


def _write(path: Path, data: bytes) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.with_name(path.name + ".partial")
        staged.write_bytes(data)
        staged.replace(path)
        return True
    except OSError:
        logger.warning("transcript %s cannot be written", path, exc_info=True)
        return False


def locate(bot_id: int, chat_id: int, session_id: str) -> Path | None:
    expected = transcript_path(bot_id, chat_id, session_id)
    if expected.exists():
        return expected
    try:
        found = next((settings.claude_config_dir / "projects").glob(f"*/{session_id}.jsonl"), None)
    except OSError:
        return None
    if found is not None:
        logger.warning(
            "transcript %s sits at %s, not at the expected %s: the project slug is wrong",
            session_id,
            found,
            expected,
        )
    return found


def _retag(line: bytes, session_id: str) -> bytes:
    try:
        entry = json.loads(line)
    except ValueError:
        return line
    if not isinstance(entry, dict) or SESSION_FIELD not in entry:
        return line
    entry[SESSION_FIELD] = session_id
    return json.dumps(entry, ensure_ascii=False).encode()


async def save(session_id: str, bot_id: int, chat_id: int) -> int:
    path = locate(bot_id, chat_id, session_id)
    data = _read(path) if path is not None else None
    if not data:
        logger.warning(
            "transcript %s left nothing on disk: this session cannot leave %s",
            session_id,
            settings.instance_id,
        )
        return 0
    if len(data) > settings.transcript_max_bytes:
        logger.error(
            "transcript %s is %s, over the limit: the session stays on %s and nowhere else",
            session_id,
            human_size(len(data)),
            settings.instance_id,
        )
        return 0
    lines = len(data.splitlines())
    async with SessionLocal() as session:
        await TranscriptRepository(session).save(
            session_id=session_id,
            bot_id=bot_id,
            chat_id=chat_id,
            body=gzip.compress(data),
            lines=lines,
            raw_bytes=len(data),
        )
    logger.info("transcript %s stored: %s line(s), %s", session_id, lines, human_size(len(data)))
    return lines


async def ensure(session_id: str, bot_id: int, chat_id: int) -> bool:
    path = transcript_path(bot_id, chat_id, session_id)
    local = path.stat().st_size if path.exists() else -1
    async with SessionLocal() as session:
        stored = await TranscriptRepository(session).get(session_id)
    if stored is None:
        return local >= 0
    if local == stored.raw_bytes:
        return True
    if local > stored.raw_bytes:
        logger.warning(
            "transcript %s is %s on disk against %s in the database, taking the database",
            session_id,
            human_size(local),
            human_size(stored.raw_bytes),
        )
    logger.info(
        "transcript %s restored from the database onto %s", session_id, settings.instance_id
    )
    return _write(path, gzip.decompress(stored.body))


async def fork(session_id: str, lines: int, bot_id: int, chat_id: int) -> str | None:
    async with SessionLocal() as session:
        stored = await TranscriptRepository(session).get(session_id)
    if stored is not None:
        data = gzip.decompress(stored.body)
    else:
        local = locate(bot_id, chat_id, session_id)
        data = _read(local) if local is not None else None
    if not data:
        return None
    every = data.splitlines()
    kept = every[:lines]
    if not kept:
        return None
    fresh = str(uuid.uuid4())
    body = b"\n".join(_retag(line, fresh) for line in kept) + b"\n"
    if not _write(transcript_path(bot_id, chat_id, fresh), body):
        return None
    async with SessionLocal() as session:
        await TranscriptRepository(session).save(
            session_id=fresh,
            bot_id=bot_id,
            chat_id=chat_id,
            body=gzip.compress(body),
            lines=len(kept),
            raw_bytes=len(body),
        )
    logger.info(
        "transcript %s forked from %s at line %s of %s -> %s",
        fresh,
        session_id,
        len(kept),
        len(every),
        human_size(len(body)),
    )
    return fresh
