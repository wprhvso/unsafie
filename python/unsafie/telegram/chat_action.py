import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from aiogram import Bot

logger = logging.getLogger(__name__)

INTERVAL = 5.0
TIMEOUT = 10.0


async def _loop(bot: Bot, chat_id: int, prefix: str) -> None:
    while True:
        try:
            await asyncio.wait_for(bot.send_chat_action(chat_id, "typing"), timeout=TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("%s typing failed: %s", prefix, e)
        await asyncio.sleep(INTERVAL)


@contextlib.asynccontextmanager
async def typing(bot: Bot, chat_id: int, prefix: str) -> AsyncIterator[None]:
    task = asyncio.create_task(_loop(bot, chat_id, prefix), name=f"typing:{prefix}")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
