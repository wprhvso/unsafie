import logging
from datetime import UTC, datetime, timedelta

from unsafie import events
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.models.ssh_watch import WatchMode
from unsafie.database.repositories.watch import WatchRepository
from unsafie.fluent import t
from unsafie.loop import Loop
from unsafie.settings import settings
from unsafie.ssh import pool, watches
from unsafie.ssh.errors import SshError
from unsafie.telegram import sender
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)

MAX_FAILS = 5
BATCH = 20


async def run_once(
    watch, host, *, locale: str | None = None
) -> tuple[bool, str, pool.Result | None]:
    condition = watches.parse(watch.condition)
    result = await pool.run(watch.user_id, host, watch.command, settings.watch_command_timeout)
    fires, reason = watches.evaluate(condition, result.output, result.exit_code, watch.last_output)
    _ = locale
    return fires, reason, result


class Watchdog(Loop):
    name = "ssh-watchdog"
    startup_delay = 20.0

    @property
    def enabled(self) -> bool:
        return settings.schedule_enabled

    @property
    def interval(self) -> float:
        return float(settings.schedule_tick)

    async def tick(self) -> None:
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            due = await WatchRepository(session).due(now, BATCH)
        for watch, host in due:
            try:
                await self._one(watch, host)
            except Exception:
                logger.exception("watch=%s failed", watch.id)
                await self._reschedule(watch, failed=True)
        await pool.pool.sweep()

    async def _reschedule(
        self, watch, failed: bool, output: str | None = None, exit_code: int | None = None
    ) -> None:
        async with SessionLocal() as session:
            repo = WatchRepository(session)
            row = await repo.get_any(watch.id)
            if row is None:
                return
            row.last_run_at = datetime.now(UTC)
            if output is not None:
                row.last_output = output[:20000]
            if exit_code is not None:
                row.last_exit = exit_code
            row.fails = row.fails + 1 if failed else 0
            delay = row.interval_sec * (2 ** min(row.fails, 4)) if failed else row.interval_sec
            row.next_run_at = datetime.now(UTC) + timedelta(seconds=delay)
            if row.fails >= MAX_FAILS:
                row.enabled = False
                logger.warning("watch=%s disabled after %s failures", row.id, row.fails)
            await repo.save()

    async def _one(self, watch, host) -> None:
        bot = manager.bot(watch.bot_id)
        if bot is None:
            logger.warning("watch=%s: bot %s is not running", watch.id, watch.bot_id)
            await self._reschedule(watch, failed=False)
            return
        try:
            fires, reason, result = await run_once(watch, host)
        except SshError as e:
            logger.warning("watch=%s ssh error: %s", watch.id, e)
            await self._reschedule(watch, failed=True)
            async with SessionLocal() as session:
                row = await WatchRepository(session).get_any(watch.id)
                if row and row.fails == MAX_FAILS:
                    await sender.send(
                        bot,
                        bot_id=watch.bot_id,
                        chat_id=watch.chat_id,
                        markdown=t(
                            "ssh-watch-disabled",
                            None,
                            name=watch.name,
                            alias=host.alias,
                            error=str(e),
                        ),
                        kind=ResponseKind.SYSTEM,
                    )
            return
        was_alerting = watch.alerting
        await self._reschedule(
            watch, failed=False, output=result.output, exit_code=result.exit_code
        )
        async with SessionLocal() as session:
            row = await WatchRepository(session).get_any(watch.id)
            if row is not None:
                row.alerting = fires
                await WatchRepository(session).save()
        if fires and not was_alerting:
            events.publish(
                "watch.fired",
                watch_id=watch.id,
                bot_id=watch.bot_id,
                chat_id=watch.chat_id,
                name=watch.name,
                host=host.alias,
                reason=reason,
            )
            await self._notify(bot, watch, host, result, reason, recovered=False)
        elif was_alerting and not fires:
            events.publish(
                "watch.recovered",
                watch_id=watch.id,
                bot_id=watch.bot_id,
                chat_id=watch.chat_id,
                name=watch.name,
                host=host.alias,
            )
            await self._notify(bot, watch, host, result, reason, recovered=True)

    async def _notify(self, bot, watch, host, result, reason: str, recovered: bool) -> None:
        if watch.mode == WatchMode.TASK and not recovered:
            from unsafie.agent.runtime import run_watch

            await run_watch(bot, watch, host, result.output, result.exit_code)
            return
        key = "ssh-watch-recovered" if recovered else "ssh-watch-fired"
        text = t(
            key,
            None,
            name=watch.name,
            alias=host.alias,
            condition=watch.condition,
            reason=reason,
            output=(result.output or "")[-1500:],
        )
        await sender.send(
            bot, bot_id=watch.bot_id, chat_id=watch.chat_id, markdown=text, kind=ResponseKind.SYSTEM
        )


watchdog = Watchdog()
