import logging
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.ssh_host import SshHost
from unsafie.database.models.ssh_watch import SshWatch

logger = logging.getLogger(__name__)


class WatchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, **fields) -> SshWatch:
        row = SshWatch(**fields)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        logger.info("watch=%s created host=%s every=%ss", row.id, row.host_id, row.interval_sec)
        return row

    async def get(self, bot_id: int, chat_id: int, watch_id: int) -> SshWatch | None:
        row = await self.session.get(SshWatch, watch_id)
        if row is None or row.bot_id != bot_id or row.chat_id != chat_id:
            return None
        return row

    async def get_any(self, watch_id: int) -> SshWatch | None:
        return await self.session.get(SshWatch, watch_id)

    async def for_chat(self, bot_id: int, chat_id: int) -> list[tuple[SshWatch, SshHost]]:
        rows = await self.session.execute(
            select(SshWatch, SshHost)
            .join(SshHost, SshHost.id == SshWatch.host_id)
            .where(SshWatch.bot_id == bot_id, SshWatch.chat_id == chat_id)
            .order_by(SshWatch.id)
        )
        return [(w, h) for w, h in rows.all()]

    async def count_for_chat(self, bot_id: int, chat_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(SshWatch)
                .where(SshWatch.bot_id == bot_id, SshWatch.chat_id == chat_id)
            )
            or 0
        )

    async def due(self, now: datetime, limit: int = 50) -> list[tuple[SshWatch, SshHost]]:
        rows = await self.session.execute(
            select(SshWatch, SshHost)
            .join(SshHost, SshHost.id == SshWatch.host_id)
            .where(SshWatch.enabled.is_(True), SshWatch.next_run_at <= now)
            .order_by(SshWatch.next_run_at)
            .limit(limit)
        )
        return [(w, h) for w, h in rows.all()]

    async def remove(self, bot_id: int, chat_id: int, watch_id: int) -> bool:
        row = await self.get(bot_id, chat_id, watch_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def remove_all(self, bot_id: int, chat_id: int) -> int:
        result = await self.session.execute(
            delete(SshWatch).where(SshWatch.bot_id == bot_id, SshWatch.chat_id == chat_id)
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def save(self) -> None:
        await self.session.commit()

    async def page(
        self, offset: int = 0, limit: int = 50
    ) -> tuple[list[tuple[SshWatch, SshHost]], int]:
        total = await self.session.scalar(select(func.count()).select_from(SshWatch)) or 0
        rows = await self.session.execute(
            select(SshWatch, SshHost)
            .join(SshHost, SshHost.id == SshWatch.host_id)
            .order_by(SshWatch.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(w, h) for w, h in rows.all()], int(total)
