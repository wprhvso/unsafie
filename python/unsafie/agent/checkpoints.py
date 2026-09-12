import json
from unsafie.log import get_logger
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.repositories.checkpoint import CheckpointRepository
from unsafie.settings import settings

logger = get_logger(__name__)


@dataclass(frozen=True)
class CheckpointData:
    turn_id: UUID
    step: int
    phase: str
    messages: list[dict]
    active_block: dict | None = None
    injected: dict | list | None = None
    credential_id: int | None = None
    created_at: datetime | None = None


def cache_key(turn_id: UUID | str) -> str:
    return cluster.key("checkpoint", str(turn_id))


async def save(
    turn_id: UUID,
    step: int,
    phase: str,
    messages: list[dict],
    *,
    active_block: dict | None = None,
    injected: dict | list | None = None,
    credential_id: int | None = None,
) -> CheckpointData:
    async with SessionLocal() as session:
        repo = CheckpointRepository(session)
        row = await repo.save(
            turn_id=turn_id,
            step=step,
            phase=phase,
            messages=messages,
            active_block=active_block,
            injected=injected,
            credential_id=credential_id,
        )
        data = CheckpointData(
            turn_id=turn_id,
            step=step,
            phase=phase,
            messages=messages,
            active_block=active_block,
            injected=injected,
            credential_id=credential_id,
            created_at=row.created_at,
        )

    try:
        redis = cluster.client()
        payload = json.dumps(
            {
                "turn_id": str(turn_id),
                "step": step,
                "phase": phase,
                "messages": messages,
                "active_block": active_block,
                "injected": injected,
                "credential_id": credential_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            },
            ensure_ascii=False,
        )
        await redis.set(cache_key(turn_id), payload, ex=int(settings.queue_ttl))
    except Exception:
        logger.warning("failed to update checkpoint redis cache turn=%s", turn_id, exc_info=True)

    return data


async def load(turn_id: UUID) -> CheckpointData | None:
    try:
        redis = cluster.client()
        raw = await redis.get(cache_key(turn_id))
        if raw:
            item = json.loads(raw)
            created_at = None
            if item.get("created_at"):
                created_at = datetime.fromisoformat(item["created_at"])
            return CheckpointData(
                turn_id=UUID(item["turn_id"]),
                step=item["step"],
                phase=item["phase"],
                messages=item["messages"],
                active_block=item.get("active_block"),
                injected=item.get("injected"),
                credential_id=item.get("credential_id"),
                created_at=created_at,
            )
    except Exception:
        logger.warning("failed to read checkpoint from redis turn=%s", turn_id, exc_info=True)

    async with SessionLocal() as session:
        repo = CheckpointRepository(session)
        row = await repo.latest(turn_id)
        if row is None:
            return None
        messages = repo.unpack(row)
        data = CheckpointData(
            turn_id=row.turn_id,
            step=row.step,
            phase=row.phase,
            messages=messages,
            active_block=row.active_block,
            injected=row.injected,
            credential_id=row.credential_id,
            created_at=row.created_at,
        )

    try:
        redis = cluster.client()
        payload = json.dumps(
            {
                "turn_id": str(turn_id),
                "step": data.step,
                "phase": data.phase,
                "messages": data.messages,
                "active_block": data.active_block,
                "injected": data.injected,
                "credential_id": data.credential_id,
                "created_at": data.created_at.isoformat() if data.created_at else None,
            },
            ensure_ascii=False,
        )
        await redis.set(cache_key(turn_id), payload, ex=int(settings.queue_ttl))
    except Exception:
        pass

    return data


async def clear(turn_id: UUID) -> None:
    try:
        redis = cluster.client()
        await redis.delete(cache_key(turn_id))
    except Exception:
        logger.warning("failed to delete checkpoint from redis turn=%s", turn_id, exc_info=True)

    async with SessionLocal() as session:
        repo = CheckpointRepository(session)
        await repo.prune(turn_id, keep_last=1)
