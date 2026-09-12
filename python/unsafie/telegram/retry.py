import asyncio
from unsafie.log import get_logger
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from unsafie import telemetry
from unsafie.fluent import t

logger = get_logger(__name__)


class RetryCallback(CallbackData, prefix="retry"):
    turn_id: str


def retry_markup(turn_id: str, locale: str, in_progress: bool = False) -> InlineKeyboardMarkup:
    if in_progress:
        text = t("commands-retry-in-progress", locale)
        button = InlineKeyboardButton(text=text, callback_data="noop")
    else:
        text = t("commands-retry-button", locale)
        button = InlineKeyboardButton(
            text=text, callback_data=RetryCallback(turn_id=str(turn_id)).pack(),
        )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


async def retry[T](fn: Callable[[], Awaitable[T]], what: str, attempts: int = 3) -> T:
    for attempt in range(attempts):
        try:
            return await fn()
        except TelegramRetryAfter as e:
            if attempt == attempts - 1:
                raise
            telemetry.event(
                "telegram.rate_limited", {"attempt": attempt + 1, "retry_after": e.retry_after},
            )
            logger.warning("%s rate limited retry_after=%ss", what, e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramNetworkError as e:
            if attempt == attempts - 1:
                raise
            delay = 2**attempt
            telemetry.event("telegram.network_error", {"attempt": attempt + 1, "retry_in": delay})
            logger.warning("%s network error=%s retry_in=%ss", what, e, delay)
            await asyncio.sleep(delay)
    raise RuntimeError(f"{what} failed after {attempts} attempts")


async def download(bot: Bot, file_id: str, what: str) -> bytes:
    async def _fetch() -> bytes:
        with tempfile.NamedTemporaryFile(prefix="tg_dl_") as tmp:
            tmp_path = Path(tmp.name)
            await bot.download(file_id, destination=tmp_path)
            return tmp_path.read_bytes()

    return await retry(_fetch, what)
