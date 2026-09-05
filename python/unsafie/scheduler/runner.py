import logging
from datetime import UTC, datetime

from unsafie import events
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.models.scheduled_task import TaskKind
from unsafie.database.repositories.schedule import ScheduleRepository
from unsafie.fluent import t
from unsafie.loop import Loop
from unsafie.scheduler import service
from unsafie.settings import settings
from unsafie.telegram import sender
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)

BATCH = 20


class Runner(Loop):
    name = "scheduler"
    startup_delay = 10.0

    @property
    def enabled(self) -> bool:
        return settings.schedule_enabled

    @property
    def interval(self) -> float:
        return float(settings.schedule_tick)

    async def tick(self) -> None:
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            due = await ScheduleRepository(session).due(now, BATCH)
        for task in due:
            try:
                await self._fire(task)
            except Exception:
                logger.exception("task=%s failed", task.id)
                await self._advance(task)

    async def _advance(self, task) -> None:
        run_at = await service.advance(task)
        async with SessionLocal() as session:
            repo = ScheduleRepository(session)
            row = await repo.get_any(task.id)
            if row is not None:
                await repo.fired(row, run_at)

    async def _fire(self, task) -> None:
        bot = manager.bot(task.bot_id)
        if bot is None:
            logger.warning("task=%s: bot %s is not running", task.id, task.bot_id)
            await self._advance(task)
            return
        events.publish(
            "task.fired",
            task_id=task.id,
            bot_id=task.bot_id,
            chat_id=task.chat_id,
            kind=str(task.kind),
            text=task.text[:120],
        )
        logger.info("task=%s firing kind=%s chat=%s", task.id, task.kind, task.chat_id)
        if task.kind == TaskKind.REMIND:
            await sender.send(
                bot,
                bot_id=task.bot_id,
                chat_id=task.chat_id,
                markdown=t("tasks-reminder", None, text=task.text),
                kind=ResponseKind.SYSTEM,
                reply_to=task.origin_message_id,
            )
        else:
            from unsafie.agent.runtime import run_scheduled

            await run_scheduled(bot, task)
        await self._advance(task)


runner = Runner()
