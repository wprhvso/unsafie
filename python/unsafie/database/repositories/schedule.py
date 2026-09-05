import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.scheduled_task import ScheduledTask

logger = logging.getLogger(__name__)


class ScheduleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, **fields) -> ScheduledTask:
        task = ScheduledTask(**fields)
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        logger.info(
            "task=%s created chat=%s kind=%s next=%s",
            task.id,
            task.chat_id,
            task.kind,
            task.next_run_at,
        )
        return task

    async def get(self, bot_id: int, chat_id: int, task_id: int) -> ScheduledTask | None:
        task = await self.session.get(ScheduledTask, task_id)
        if task is None or task.bot_id != bot_id or task.chat_id != chat_id:
            return None
        return task

    async def get_any(self, task_id: int) -> ScheduledTask | None:
        return await self.session.get(ScheduledTask, task_id)

    async def for_chat(self, bot_id: int, chat_id: int) -> list[ScheduledTask]:
        rows = await self.session.scalars(
            select(ScheduledTask)
            .where(ScheduledTask.bot_id == bot_id, ScheduledTask.chat_id == chat_id)
            .order_by(ScheduledTask.next_run_at)
        )
        return list(rows)

    async def count_for_chat(self, bot_id: int, chat_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(ScheduledTask)
                .where(ScheduledTask.bot_id == bot_id, ScheduledTask.chat_id == chat_id)
            )
            or 0
        )

    async def due(self, now: datetime, limit: int = 50) -> list[ScheduledTask]:
        rows = await self.session.scalars(
            select(ScheduledTask)
            .where(ScheduledTask.enabled.is_(True), ScheduledTask.next_run_at <= now)
            .order_by(ScheduledTask.next_run_at)
            .limit(limit)
        )
        return list(rows)

    async def fired(self, task: ScheduledTask, next_run_at: datetime | None) -> None:
        task.runs += 1
        task.last_run_at = datetime.now(UTC)
        if next_run_at is None:
            await self.session.delete(task)
        else:
            task.next_run_at = next_run_at
        await self.session.commit()

    async def set_enabled(self, task: ScheduledTask, enabled: bool) -> None:
        task.enabled = enabled
        await self.session.commit()

    async def remove(self, bot_id: int, chat_id: int, task_id: int) -> bool:
        task = await self.get(bot_id, chat_id, task_id)
        if task is None:
            return False
        await self.session.delete(task)
        await self.session.commit()
        return True

    async def remove_all(self, bot_id: int, chat_id: int) -> int:
        result = await self.session.execute(
            delete(ScheduledTask).where(
                ScheduledTask.bot_id == bot_id, ScheduledTask.chat_id == chat_id
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[ScheduledTask], int]:
        total = await self.session.scalar(select(func.count()).select_from(ScheduledTask)) or 0
        rows = await self.session.scalars(
            select(ScheduledTask).order_by(ScheduledTask.next_run_at).offset(offset).limit(limit)
        )
        return list(rows), int(total)
