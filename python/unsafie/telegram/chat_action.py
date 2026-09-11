import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from aiogram import Bot

logger = logging.getLogger(__name__)

INTERVAL = 4.5
TIMEOUT = 8.0

_active_chats: dict[tuple[int, int], int] = {}
_tasks: dict[tuple[int, int], asyncio.Task] = {}
_lock = asyncio.Lock()


async def _loop(bot: Bot, chat_id: int) -> None:
    while True:
        try:
            await asyncio.wait_for(bot.send_chat_action(chat_id, "typing"), timeout=TIMEOUT)
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(INTERVAL)


@contextlib.asynccontextmanager
async def typing(bot: Bot, chat_id: int, prefix: str = "") -> AsyncIterator[None]:
    key = (bot.id, chat_id)
    async with _lock:
        count = _active_chats.get(key, 0) + 1
        _active_chats[key] = count
        if count == 1:
            _tasks[key] = asyncio.create_task(_loop(bot, chat_id), name=f"typing:{chat_id}")
    try:
        yield
    finally:
        async with _lock:
            count = _active_chats.get(key, 1) - 1
            if count <= 0:
                _active_chats.pop(key, None)
                task = _tasks.pop(key, None)
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            else:
                _active_chats[key] = count
