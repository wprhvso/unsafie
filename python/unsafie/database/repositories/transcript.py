import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.transcript import Transcript

logger = logging.getLogger(__name__)


class TranscriptRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, session_id: str) -> Transcript | None:
        return await self.session.get(Transcript, session_id)

    async def size(self, session_id: str) -> int | None:
        return await self.session.scalar(
            select(Transcript.raw_bytes).where(Transcript.session_id == session_id)
        )

    async def save(
        self,
        *,
        session_id: str,
        bot_id: int,
        chat_id: int,
        body: bytes,
        lines: int,
        raw_bytes: int,
    ) -> None:
        values = {
            "session_id": session_id,
            "bot_id": bot_id,
            "chat_id": chat_id,
            "body": body,
            "lines": lines,
            "raw_bytes": raw_bytes,
            "updated_at": datetime.now(UTC),
        }
        stmt = insert(Transcript).values(**values)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Transcript.session_id],
                set_={k: v for k, v in values.items() if k != "session_id"},
            )
        )
        await self.session.commit()

    async def purge(self, keep_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=keep_days)
        result = await self.session.execute(
            delete(Transcript).where(Transcript.updated_at < cutoff)
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def total_bytes(self) -> int:
        return int(await self.session.scalar(select(func.sum(Transcript.raw_bytes))) or 0)
