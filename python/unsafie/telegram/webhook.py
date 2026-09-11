import contextlib
import hashlib
import logging
import time

from aiogram import Dispatcher
from aiogram.exceptions import TelegramAPIError

from unsafie import cluster, events
from unsafie.database import SessionLocal
from unsafie.database.repositories.bot import BotRepository
from unsafie.loop import Loop
from unsafie.settings import settings
from unsafie.telegram import bots
from unsafie.telegram.handlers import build_router
from unsafie.telegram.middleware import UpdateMiddleware

logger = logging.getLogger(__name__)

dispatcher = Dispatcher()
dispatcher.update.outer_middleware(UpdateMiddleware())
dispatcher.include_router(build_router())


def mark_name(bot_id: int) -> str:
    return f"bot:{bot_id}:webhook"


def restart_name(bot_id: int) -> str:
    return f"bot:{bot_id}:restart"


def secret_token_for(token: str) -> str:
    secret = settings.telegram_webhook_secret or ""
    data = f"unsafie:{token}:{secret}".encode()
    return hashlib.sha256(data).hexdigest()


def webhook_url(bot_id: int) -> str:
    base = (
        settings.telegram_webhook_base_url.rstrip("/")
        if settings.telegram_webhook_base_url
        else f"{settings.public_origin}/api/telegram/webhook"
    )
    return f"{base}/{bot_id}"


async def mark_active(bot_id: int) -> None:
    with contextlib.suppress(Exception):
        await cluster.mark(mark_name(bot_id), "1", settings.telegram_webhook_sync_interval * 3)


async def unmark_active(bot_id: int) -> None:
    with contextlib.suppress(Exception):
        await cluster.client().delete(cluster.key("mark", mark_name(bot_id)))


async def ensure_webhook(bot_id: int, token: str, *, force: bool = False) -> None:
    bot = bots.build(token)
    try:
        me = await bot.get_me()
        url = webhook_url(bot_id)
        secret = secret_token_for(token)
        try:
            info = await bot.get_webhook_info()
            if force or info.url != url:
                allowed = sorted({*dispatcher.resolve_used_update_types(), "edited_message"})
                await bot.set_webhook(
                    url=url,
                    secret_token=secret,
                    allowed_updates=allowed,
                    drop_pending_updates=False,
                )
                logger.info(
                    "bot=%s webhook configured: %s as @%s (tg_id=%s)",
                    bot_id,
                    url,
                    me.username,
                    me.id,
                )
                events.publish(
                    "bot.started",
                    bot_id=bot_id,
                    username=me.username,
                    instance=settings.instance_id,
                )
            await mark_active(bot_id)
        except TelegramAPIError as e:
            logger.warning("bot=%s could not configure webhook: %s", bot_id, e)
            events.publish(
                "bot.crashed",
                bot_id=bot_id,
                instance=settings.instance_id,
                error=str(e)[:500],
            )
        async with SessionLocal() as session:
            await BotRepository(session).set_identity(bot_id, me.id, me.username or "")
    finally:
        await bot.session.close()


async def delete_webhook(bot_id: int, token: str) -> None:
    bot = bots.build(token)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        events.publish(
            "bot.stopped",
            bot_id=bot_id,
            instance=settings.instance_id,
            reason="webhook deleted",
        )
        logger.info("bot=%s webhook deleted", bot_id)
    except Exception:
        logger.warning("bot=%s could not delete webhook", bot_id, exc_info=True)
    finally:
        await bot.session.close()
    await unmark_active(bot_id)


async def request_restart(bot_id: int) -> None:
    await cluster.mark(restart_name(bot_id), str(time.time_ns()), 86_400.0)
    logger.info("bot=%s restart requested by %s", bot_id, settings.instance_id)


async def polled_by(bot_ids: list[int]) -> dict[int, str | None]:
    try:
        marks = await cluster.marks([mark_name(b) for b in bot_ids])
        return {b: ("webhook" if marks.get(mark_name(b)) else None) for b in bot_ids}
    except Exception:
        return dict.fromkeys(bot_ids)


class Supervisor(Loop):
    name = "telegram-webhook"
    startup_delay = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._synced: set[int] = set()

    @property
    def enabled(self) -> bool:
        return settings.runs_web or settings.runs_poller

    @property
    def interval(self) -> float:
        return settings.telegram_webhook_sync_interval

    @property
    def min_interval(self) -> float:
        return 5.0

    def ids(self) -> list[int]:
        return sorted(self._synced)

    async def tick(self) -> None:
        async with SessionLocal() as session:
            bots_list = await BotRepository(session).all()
        wanted = {b.id: b.token for b in bots_list}
        restarts = await cluster.marks([restart_name(b) for b in wanted])

        active = set()
        for bot_id, token in wanted.items():
            force = restarts.get(restart_name(bot_id)) is not None
            if not force and bot_id in self._synced:
                active.add(bot_id)
                continue
            try:
                await ensure_webhook(bot_id, token, force=force)
                if force:
                    with contextlib.suppress(Exception):
                        await cluster.client().delete(cluster.key("mark", restart_name(bot_id)))
                active.add(bot_id)
            except Exception as e:
                logger.warning("bot=%s sync webhook failed: %s", bot_id, e)

        self._synced = active

    async def pause(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass


supervisor = Supervisor()


async def reconcile() -> None:
    if supervisor.enabled:
        await supervisor.tick()
