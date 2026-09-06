import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from unsafie import events, telemetry
from unsafie.telegram.handlers import build_router
from unsafie.telegram.middleware import UpdateMiddleware
from unsafie.telegram.tracing import ApiTracing

logger = logging.getLogger(__name__)


class RunningBot:
    def __init__(self, bot: Bot, dispatcher: Dispatcher, task: asyncio.Task, username: str) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.task = task
        self.username = username


class BotManager:
    def __init__(self) -> None:
        self._running: dict[int, RunningBot] = {}

    def is_running(self, bot_id: int) -> bool:
        return bot_id in self._running

    def running_ids(self) -> list[int]:
        return sorted(self._running)

    def bot(self, bot_id: int) -> Bot | None:
        running = self._running.get(bot_id)
        return running.bot if running else None

    def username(self, bot_id: int) -> str | None:
        running = self._running.get(bot_id)
        return running.username if running else None

    async def start(self, bot_id: int, token: str) -> None:
        if bot_id in self._running:
            return
        bot = Bot(token=token, default=DefaultBotProperties(link_preview_is_disabled=True))
        bot.session.middleware(ApiTracing())
        try:
            me = await bot.get_me()
        except Exception:
            await bot.session.close()
            raise
        logger.info("bot=%s authorized as @%s (tg_id=%s)", bot_id, me.username, me.id)
        dispatcher = Dispatcher()
        dispatcher.update.outer_middleware(UpdateMiddleware(bot_id))
        dispatcher.include_router(build_router())
        # Polling outlives whatever asked to start the bot; a trace must not follow it there.
        with telemetry.detached():
            task = asyncio.create_task(
                dispatcher.start_polling(bot, handle_signals=False, bot_id=bot_id),
                name=f"bot-{bot_id}",
            )
        task.add_done_callback(lambda t: self._on_done(bot_id, t))
        self._running[bot_id] = RunningBot(bot, dispatcher, task, me.username or "")
        events.publish("bot.started", bot_id=bot_id, username=me.username)
        logger.info("bot=%s polling started, running=%s", bot_id, self.running_ids())

    async def stop(self, bot_id: int) -> None:
        running = self._running.pop(bot_id, None)
        if running is None:
            return
        running.task.cancel()
        try:
            await running.task
        except asyncio.CancelledError:
            pass
        await running.bot.session.close()
        events.publish("bot.stopped", bot_id=bot_id)
        logger.info("bot=%s stopped, running=%s", bot_id, self.running_ids())

    async def restart(self, bot_id: int, token: str) -> None:
        await self.stop(bot_id)
        await self.start(bot_id, token)

    async def stop_all(self) -> None:
        for bot_id in list(self._running):
            await self.stop(bot_id)

    async def feed(self, data: dict) -> bool:
        from aiogram.types import Update

        item = next(iter(self._running.items()), None)
        if item is None:
            return False
        bot_id, running = item
        update = Update.model_validate(data)
        await running.dispatcher.feed_update(running.bot, update, bot_id=bot_id)
        return True

    def _on_done(self, bot_id: int, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        if exc := task.exception():
            logger.error("bot=%s polling crashed", bot_id, exc_info=exc)
            self._running.pop(bot_id, None)
            events.publish("bot.crashed", bot_id=bot_id, error=str(exc)[:500])
        else:
            logger.warning("bot=%s polling task exited without error", bot_id)


manager = BotManager()
