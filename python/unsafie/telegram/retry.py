import asyncio
import logging
from collections.abc import Awaitable, Callable
from io import BytesIO

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter

logger = logging.getLogger(__name__)


async def retry[T](fn: Callable[[], Awaitable[T]], what: str, attempts: int = 3) -> T:
    for attempt in range(attempts):
        try:
            return await fn()
        except TelegramRetryAfter as e:
            logger.warning("%s rate limited retry_after=%ss", what, e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramNetworkError as e:
            if attempt == attempts - 1:
                raise
            delay = 2**attempt
            logger.warning("%s network error=%s retry_in=%ss", what, e, delay)
            await asyncio.sleep(delay)
    return await fn()


async def download(bot: Bot, file_id: str, what: str) -> bytes:
    buf = BytesIO()
    await retry(lambda: bot.download(file_id, destination=buf), what)
    return buf.getvalue()
