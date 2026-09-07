import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.turn_message import TurnMessages

logger = logging.getLogger(__name__)

LINEAGE = text("""
WITH RECURSIVE lineage AS (
    SELECT id, parent_id, 0 AS depth
    FROM turns
    WHERE id = CAST(:turn_id AS uuid)
    UNION ALL
    SELECT t.id, t.parent_id, l.depth + 1
    FROM lineage l
    JOIN turns t ON t.id = l.parent_id
    WHERE l.depth < CAST(:max_depth AS integer)
)
SELECT l.depth, m.bytes, m.body, m.system
FROM lineage l
JOIN turn_messages m ON m.turn_id = l.id
ORDER BY l.depth DESC
""")

PURGE = text("""
DELETE FROM turn_messages m
USING turns t
WHERE m.turn_id = t.id
  AND t.root_id IN (
      SELECT root_id FROM turns GROUP BY root_id HAVING max(created_at) < CAST(:cutoff AS timestamptz)
  )
""")


@dataclass(frozen=True)
class Lineage:
    bodies: list[bytes]
    system: str | None
    segments: int
    dropped: int
    bytes: int


class SegmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lineage(self, turn_id: UUID, *, max_depth: int, budget: int) -> Lineage:
        rows = (
            await self.session.execute(
                LINEAGE, {"turn_id": str(turn_id), "max_depth": max_depth}
            )
        ).all()
        if not rows:
            return Lineage([], None, 0, 0, 0)
        kept: list = []
        total = 0
        for row in reversed(rows):
            if kept and total + row.bytes > budget:
                break
            kept.append(row)
            total += row.bytes
        kept.reverse()
        dropped = len(rows) - len(kept)
        if dropped:
            logger.info(
                "history for turn=%s trimmed: kept %s of %s segment(s), %s bytes",
                turn_id,
                len(kept),
                len(rows),
                total,
            )
        return Lineage([r.body for r in kept], rows[0].system, len(kept), dropped, total)

    async def save(
        self, turn_id: UUID, *, body: bytes, count: int, size: int, system: str | None
    ) -> None:
        values = {
            "turn_id": turn_id,
            "body": body,
            "count": count,
            "bytes": size,
            "system": system,
        }
        stmt = insert(TurnMessages).values(**values)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[TurnMessages.turn_id],
                set_={k: v for k, v in values.items() if k != "turn_id"},
            )
        )
        await self.session.commit()

    async def purge(self, keep_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=keep_days)
        result = await self.session.execute(PURGE, {"cutoff": cutoff})
        await self.session.commit()
        return int(result.rowcount or 0)

    async def total_bytes(self) -> int:
        return int(await self.session.scalar(select(func.sum(TurnMessages.bytes))) or 0)
