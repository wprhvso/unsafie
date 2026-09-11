import hashlib
import logging

from aiogram import Dispatcher

from unsafie import cluster
from unsafie.settings import settings
from unsafie.telegram.engine import telegram_engine
from unsafie.telegram.handlers import build_router
from unsafie.telegram.middleware import UpdateMiddleware

logger = logging.getLogger(__name__)

dispatcher = Dispatcher()
dispatcher.update.outer_middleware(UpdateMiddleware())
dispatcher.include_router(build_router())

supervisor = telegram_engine


def mark_name(bot_id: int) -> str:
    return f"bot:{bot_id}:webhook"


def restart_name(bot_id: int) -> str:
    return f"bot:{bot_id}:restart"


def secret_token_for(token: str) -> str:
    secret = settings.telegram_webhook_secret or ""
    data = f"unsafie:{token}:{secret}".encode()
    return hashlib.sha256(data).hexdigest()


def webhook_url(bot_id: int) -> str:
    return f"{settings.public_origin}/api/telegram/webhook/{bot_id}"


async def mark_active(bot_id: int) -> None:
    pass


async def unmark_active(bot_id: int) -> None:
    pass


async def ensure_webhook(bot_id: int, token: str, *, force: bool = False) -> None:
    await telegram_engine.tick()


async def delete_webhook(bot_id: int, token: str) -> None:
    pass


async def request_restart(bot_id: int) -> None:
    await cluster.mark(restart_name(bot_id), "1", 86400.0)


async def polled_by(bot_ids: list[int]) -> dict[int, str | None]:
    return {b: "polling" for b in bot_ids}


async def reconcile() -> None:
    await telegram_engine.tick()
