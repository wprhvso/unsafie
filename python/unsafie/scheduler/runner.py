import asyncio
from unsafie.log import get_logger
from datetime import UTC, datetime, timedelta

from unsafie import events, telemetry
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.models.scheduled_task import TaskKind
from unsafie.database.repositories.schedule import ScheduleRepository
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.loop import Loop
from unsafie.scheduler import service
from unsafie.settings import settings
from unsafie.telegram import bots, sender
from unsafie.telemetry import attrs

logger = get_logger(__name__)

BATCH = 20


class Runner(Loop):
    name = "scheduler"
    startup_delay = 10.0

    @property
    def enabled(self) -> bool:
        return settings.schedule_enabled and settings.runs_worker

    @property
    def interval(self) -> float:
        return float(settings.schedule_tick)

    async def tick(self) -> None:
        now = datetime.now(UTC)
        with telemetry.muted():
            async with SessionLocal() as session:
                due = await ScheduleRepository(session).claim(now, BATCH, settings.job_lease)
        for task in due:
            t = asyncio.create_task(self._safe_fire(task))
            _ = t

    async def _safe_fire(self, task) -> None:
        with telemetry.span(
            "scheduler.task",
            kind=telemetry.CONSUMER,
            attributes={
                attrs.TASK_ID: task.id,
                attrs.TASK_KIND: str(task.kind),
                attrs.BOT_ID: task.bot_id,
                attrs.CHAT_ID: task.chat_id,
                attrs.USER_ID: task.user_id,
                attrs.PROMPT: telemetry.content(task.text),
            },
        ) as span:
            try:
                await self._fire(task)
            except Exception as e:
                telemetry.fail(span, e)
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
        bot = await bots.bot_for(task.bot_id)
        if bot is None:
            logger.warning("task=%s: bot %s is not running, retrying in 15s", task.id, task.bot_id)
            async with SessionLocal() as session:
                repo = ScheduleRepository(session)
                row = await repo.get_any(task.id)
                if row is not None:
                    row.next_run_at = datetime.now(UTC) + timedelta(seconds=15)
                    row.active_turn_id = None
                    await session.commit()
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
            locale = None
            if getattr(task, "user_id", None):
                async with SessionLocal() as session:
                    user = await UserRepository(session).get(task.user_id)
                    locale = user.locale if user and user.locale else None
            await sender.send(
                bot,
                bot_id=task.bot_id,
                chat_id=task.chat_id,
                markdown=t("tasks-reminder", locale, text=task.text),
                kind=ResponseKind.SYSTEM,
                reply_to=task.origin_message_id,
            )
        else:
            from unsafie.agent.runtime import run_scheduled

            await run_scheduled(bot, task)
        await self._advance(task)


runner = Runner()
