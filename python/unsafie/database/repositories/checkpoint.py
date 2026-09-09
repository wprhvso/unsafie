import gzip
import json
import logging
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.turn import Turn
from unsafie.database.models.turn_checkpoint import TurnCheckpoint

logger = logging.getLogger(__name__)


class CheckpointRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        *,
        turn_id: UUID,
        step: int,
        phase: str,
        messages: list[dict],
        active_block: dict | None = None,
        injected: dict | list | None = None,
        credential_id: int | None = None,
    ) -> TurnCheckpoint:
        encoded = json.dumps(messages, ensure_ascii=False).encode("utf-8")
        compressed = gzip.compress(encoded)
        values = {
            "turn_id": turn_id,
            "step": step,
            "phase": phase,
            "messages": compressed,
            "active_block": active_block,
            "injected": injected,
            "credential_id": credential_id,
        }
        stmt = insert(TurnCheckpoint).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_turn_checkpoints_step_phase",
            set_={
                "messages": compressed,
                "active_block": active_block,
                "injected": injected,
                "credential_id": credential_id,
            },
        ).returning(TurnCheckpoint)
        checkpoint = await self.session.scalar(stmt)
        assert checkpoint is not None

        turn_update = {"last_checkpoint_step": step}
        if active_block and active_block.get("spool_dir"):
            turn_update["active_spool_dir"] = str(active_block["spool_dir"])

        await self.session.execute(
            update(Turn).where(Turn.id == turn_id).values(**turn_update)
        )
        await self.session.commit()
        return checkpoint

    async def latest(self, turn_id: UUID) -> TurnCheckpoint | None:
        return await self.session.scalar(
            select(TurnCheckpoint)
            .where(TurnCheckpoint.turn_id == turn_id)
            .order_by(TurnCheckpoint.step.desc(), TurnCheckpoint.created_at.desc())
            .limit(1)
        )

    def unpack(self, checkpoint: TurnCheckpoint) -> list[dict]:
        try:
            raw = gzip.decompress(checkpoint.messages)
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("failed to unpack checkpoint messages turn=%s step=%s", checkpoint.turn_id, checkpoint.step)
            return []

    async def for_step(self, turn_id: UUID, step: int) -> list[TurnCheckpoint]:
        rows = await self.session.scalars(
            select(TurnCheckpoint)
            .where(TurnCheckpoint.turn_id == turn_id, TurnCheckpoint.step == step)
            .order_by(TurnCheckpoint.created_at.desc())
        )
        return list(rows)

    async def prune(self, turn_id: UUID, keep_last: int = 1) -> int:
        subq = (
            select(TurnCheckpoint.id)
            .where(TurnCheckpoint.turn_id == turn_id)
            .order_by(TurnCheckpoint.step.desc(), TurnCheckpoint.created_at.desc())
            .limit(keep_last)
        )
        keep_ids = list(await self.session.scalars(subq))
        if not keep_ids:
            return 0
        result = await self.session.execute(
            delete(TurnCheckpoint).where(
                TurnCheckpoint.turn_id == turn_id,
                TurnCheckpoint.id.not_in(keep_ids),
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def delete_all(self, turn_id: UUID) -> int:
        result = await self.session.execute(
            delete(TurnCheckpoint).where(TurnCheckpoint.turn_id == turn_id)
        )
        await self.session.commit()
        return int(result.rowcount or 0)
