import asyncio
import contextlib

import aiohttp

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.repositories.bot import BotRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.log import get_logger
from unsafie.loop import Loop
from unsafie.settings import settings
from unsafie.telegram import bots

logger = get_logger(__name__)

inbox_wake_event = asyncio.Event()


class TelegramEngine(Loop):
    name = "telegram-engine"
    interval = 15.0
    startup_delay = 1.0

    def __init__(self) -> None:
        super().__init__()
        self._http: aiohttp.ClientSession | None = None
        self._poller_tasks: dict[int, asyncio.Task] = {}
        self._worker_task: asyncio.Task | None = None
        self._stopped = False
        self._leading: set[int] = set()

    @property
    def enabled(self) -> bool:
        return settings.runs_poller or settings.runs_worker

    def start(self) -> None:
        self._stopped = False
        super().start()

    async def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
            self._http = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=55, connect=10, sock_read=45),
            )
        return self._http

    async def tick(self) -> None:
        if settings.runs_poller:
            await self._sync_pollers()
        if settings.runs_worker and (self._worker_task is None or self._worker_task.done()):
            self._worker_task = asyncio.create_task(
                self._worker_loop(), name="telegram-inbox-worker"
            )

    async def _sync_pollers(self) -> None:
        async with SessionLocal() as session:
            current_bots = await BotRepository(session).all()
        active_ids = {b.id for b in current_bots}

        for bot_id in list(self._poller_tasks):
            if bot_id not in active_ids:
                await self._stop_bot_poller(bot_id)

        for bot in current_bots:
            task = self._poller_tasks.get(bot.id)
            if task is None or task.done():
                self._start_bot_poller(bot.id, bot.token)

    def _start_bot_poller(self, bot_id: int, token: str) -> None:
        poller_task = asyncio.create_task(
            self._poller_loop(bot_id, token), name=f"tg-poller:{bot_id}"
        )
        self._poller_tasks[bot_id] = poller_task

    async def _stop_bot_poller(self, bot_id: int) -> None:
        task = self._poller_tasks.pop(bot_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _poller_loop(self, bot_id: int, token: str) -> None:
        lock_name = f"poller:{bot_id}"
        http = await self._session()
        del_url = f"https://api.telegram.org/bot{token}/deleteWebhook"
        get_url = f"https://api.telegram.org/bot{token}/getUpdates"

        while not self._stopped:
            async with cluster.try_lock(lock_name, ttl=settings.poll_lock_ttl, renew=True) as held:
                if held is None:
                    await asyncio.sleep(2.0)
                    continue

                self._leading.add(bot_id)
                try:
                    try:
                        async with http.post(del_url, json={"drop_pending_updates": False}) as resp:
                            logger.info("bot=%s deleteWebhook status=%s", bot_id, resp.status)
                    except Exception as e:
                        logger.warning("bot=%s deleteWebhook failed: %s", bot_id, e)

                    async with SessionLocal() as session:
                        offset = await UpdateRepository(session).get_starting_offset(bot_id)

                    logger.info("bot=%s poller active initial_offset=%s", bot_id, offset)

                    while not held.lost.is_set() and not self._stopped:
                        try:
                            async with http.post(
                                get_url,
                                json={
                                    "offset": offset,
                                    "timeout": settings.poll_timeout,
                                    "allowed_updates": [
                                        "message",
                                        "edited_message",
                                        "callback_query",
                                        "inline_query",
                                        "chosen_inline_result",
                                        "message_reaction",
                                    ],
                                },
                            ) as resp:
                                if resp.status == 409:
                                    await asyncio.sleep(2.0)
                                    continue

                                if resp.status != 200:
                                    logger.warning("bot=%s getUpdates HTTP %s", bot_id, resp.status)
                                    await asyncio.sleep(2.0)
                                    continue

                                body = await resp.json()
                                if not body.get("ok"):
                                    logger.warning("bot=%s getUpdates not ok: %s", bot_id, body)
                                    await asyncio.sleep(2.0)
                                    continue

                                items = body.get("result", [])
                                if items:
                                    async with SessionLocal() as session:
                                        await UpdateRepository(session).save_batch(bot_id, items)
                                    offset = max(int(item["update_id"]) for item in items) + 1
                                    inbox_wake_event.set()
                        except asyncio.CancelledError:
                            return
                        except Exception as e:
                            logger.warning("bot=%s poller error: %s", bot_id, e)
                            await asyncio.sleep(1.0)
                finally:
                    self._leading.discard(bot_id)

    async def _worker_loop(self) -> None:
        from unsafie.telegram.webhook import dispatcher

        while not self._stopped:
            try:
                try:
                    await asyncio.wait_for(inbox_wake_event.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                inbox_wake_event.clear()

                while not self._stopped:
                    async with SessionLocal() as session:
                        repo = UpdateRepository(session)
                        batch = await repo.claim_pending(limit=50)

                    if not batch:
                        break

                    for item in batch:
                        bot = await bots.bot_for(item.bot_id)
                        if bot is None:
                            async with SessionLocal() as session:
                                await UpdateRepository(session).mark_failed(item.id)
                            continue
                        try:
                            await dispatcher.feed_raw_update(
                                bot, item.payload, bot_id=item.bot_id, update_db_id=item.id
                            )
                            async with SessionLocal() as session:
                                await UpdateRepository(session).mark_done(item.id)
                        except Exception:
                            logger.exception(
                                "inbox worker: failed to feed update_db_id=%s bot_id=%s",
                                item.id,
                                item.bot_id,
                            )
                            async with SessionLocal() as session:
                                await UpdateRepository(session).mark_failed(item.id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("inbox worker unhandled exception")
                await asyncio.sleep(0.5)

    async def pause(self) -> None:
        self._stopped = True
        for bot_id in list(self._poller_tasks):
            await self._stop_bot_poller(bot_id)

    def ids(self) -> list[int]:
        return sorted(self._leading)

    async def on_stop(self) -> None:
        await self.pause()
        if self._worker_task:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None
        if self._http and not self._http.closed:
            await self._http.close()
            self._http = None


telegram_engine = TelegramEngine()
