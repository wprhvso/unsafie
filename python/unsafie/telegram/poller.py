import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from unsafie import cluster, events, telemetry
from unsafie.database import SessionLocal
from unsafie.database.repositories.bot import BotRepository
from unsafie.loop import Loop
from unsafie.settings import settings
from unsafie.telegram import bots
from unsafie.telegram.handlers import build_router
from unsafie.telegram.middleware import UpdateMiddleware

logger = logging.getLogger(__name__)

RESTART_TTL = 86_400.0
PAUSE_TIMEOUT = 15.0


def lock_name(bot_id: int) -> str:
    return f"poller:{bot_id}"


def restart_name(bot_id: int) -> str:
    return f"bot:{bot_id}:restart"


def cooldown_name(bot_id: int) -> str:
    return f"bot:{bot_id}:cooldown"


async def request_restart(bot_id: int) -> None:
    await cluster.mark(restart_name(bot_id), str(time.time_ns()), RESTART_TTL)
    logger.info("bot=%s restart requested by %s", bot_id, settings.instance_id)


async def polled_by(bot_ids: list[int]) -> dict[int, str | None]:
    found = await cluster.owners([lock_name(b) for b in bot_ids])
    return {b: found.get(lock_name(b)) for b in bot_ids}


@dataclass
class Polling:
    bot_id: int
    token: str
    bot: Bot
    dispatcher: Dispatcher
    task: asyncio.Task
    held: cluster.Held
    restart_mark: str | None


class Supervisor(Loop):
    name = "telegram-poller"
    startup_delay = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._polling: dict[int, Polling] = {}
        self._busy = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return settings.runs_poller

    @property
    def interval(self) -> float:
        return settings.poll_claim_interval

    @property
    def min_interval(self) -> float:
        return 1.0

    def ids(self) -> list[int]:
        return sorted(self._polling)

    async def tick(self) -> None:
        if self._busy.locked():
            return
        async with self._busy:
            async with SessionLocal() as session:
                wanted = {row.id: row.token for row in await BotRepository(session).all()}
            marks = await cluster.marks([restart_name(b) for b in wanted])
            for bot_id in self.ids():
                await self._keep(bot_id, wanted.get(bot_id), marks.get(restart_name(bot_id)))
            for bot_id, token in wanted.items():
                if bot_id not in self._polling:
                    await self._claim(bot_id, token, marks.get(restart_name(bot_id)))

    async def pause(self) -> None:
        for bot_id in self.ids():
            polling = self._polling[bot_id]
            try:
                await asyncio.wait_for(polling.dispatcher.stop_polling(), timeout=PAUSE_TIMEOUT)
            except RuntimeError:
                continue
            except TimeoutError:
                logger.warning("bot=%s did not acknowledge the stop in %ss", bot_id, PAUSE_TIMEOUT)
                continue
            logger.info("bot=%s stopped fetching updates, lease still held", bot_id)

    async def on_stop(self) -> None:
        for bot_id in self.ids():
            await self._release(bot_id, "shutting down")

    async def _keep(self, bot_id: int, token: str | None, restart_mark: str | None) -> None:
        polling = self._polling[bot_id]
        if token is None:
            await self._release(bot_id, "the bot is gone")
            return
        if token != polling.token:
            await self._release(bot_id, "the token changed")
            return
        if restart_mark != polling.restart_mark:
            await self._release(bot_id, "a restart was requested")
            return
        if polling.task.done():
            await self._release(bot_id, "polling stopped on its own", cooldown=True)
            return
        if not await polling.held.extend():
            await self._release(bot_id, "the lock is no longer ours")

    async def _claim(self, bot_id: int, token: str, restart_mark: str | None) -> None:
        if await cluster.marked(cooldown_name(bot_id)):
            return
        held = await cluster.acquire(lock_name(bot_id), ttl=settings.poll_lock_ttl)
        if held is None:
            return
        try:
            self._polling[bot_id] = await self._start(bot_id, token, held, restart_mark)
        except Exception as e:
            await held.release()
            await cluster.mark(cooldown_name(bot_id), "1", settings.poll_failure_cooldown)
            logger.exception("bot=%s could not start polling", bot_id)
            events.publish(
                "bot.crashed", bot_id=bot_id, instance=settings.instance_id, error=str(e)[:500]
            )

    async def _start(
        self, bot_id: int, token: str, held: cluster.Held, restart_mark: str | None
    ) -> Polling:
        bot = bots.build(token)
        try:
            me = await bot.get_me()
            await bot.delete_webhook(drop_pending_updates=False)
        except Exception:
            await bot.session.close()
            raise
        async with SessionLocal() as session:
            await BotRepository(session).set_identity(bot_id, me.id, me.username or "")
        dispatcher = Dispatcher()
        dispatcher.update.outer_middleware(UpdateMiddleware(bot_id))
        dispatcher.include_router(build_router())
        with telemetry.detached():
            task = asyncio.create_task(
                dispatcher.start_polling(
                    bot,
                    handle_signals=False,
                    polling_timeout=settings.poll_timeout,
                    bot_id=bot_id,
                ),
                name=f"poller-{bot_id}",
            )
        events.publish(
            "bot.started", bot_id=bot_id, username=me.username, instance=settings.instance_id
        )
        logger.info(
            "bot=%s polling started by %s as @%s (tg_id=%s), polling=%s",
            bot_id,
            settings.instance_id,
            me.username,
            me.id,
            sorted([*self.ids(), bot_id]),
        )
        return Polling(bot_id, token, bot, dispatcher, task, held, restart_mark)

    async def _release(self, bot_id: int, why: str, cooldown: bool = False) -> None:
        polling = self._polling.pop(bot_id, None)
        if polling is None:
            return
        polling.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            try:
                await polling.task
            except Exception:
                logger.warning("bot=%s polling ended with an error", bot_id, exc_info=True)
        with contextlib.suppress(Exception):
            await polling.bot.session.close()
        if cooldown:
            await cluster.mark(cooldown_name(bot_id), "1", settings.poll_failure_cooldown)
        await polling.held.release()
        events.publish("bot.stopped", bot_id=bot_id, instance=settings.instance_id, reason=why)
        logger.info(
            "bot=%s polling stopped by %s (%s), polling=%s",
            bot_id,
            settings.instance_id,
            why,
            self.ids(),
        )


supervisor = Supervisor()


async def reconcile() -> None:
    if supervisor.enabled:
        await supervisor.tick()
