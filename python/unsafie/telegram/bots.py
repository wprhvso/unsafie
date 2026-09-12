import asyncio
from unsafie.log import get_logger
from dataclasses import dataclass

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.types import User

from unsafie.database import SessionLocal
from unsafie.database.repositories.bot import BotRepository
from unsafie.telegram.tracing import ApiTracing

logger = get_logger(__name__)


@dataclass
class Made:
    token: str
    bot: Bot


_made: dict[int, Made] = {}
_lock = asyncio.Lock()


def build(token: str) -> Bot:
    bot = Bot(token=token, default=DefaultBotProperties(link_preview_is_disabled=True))
    bot.session.middleware(ApiTracing())
    return bot


async def identify(token: str) -> User:
    bot = build(token)
    try:
        return await bot.get_me()
    finally:
        await bot.session.close()


async def bot_for(bot_id: int) -> Bot | None:
    async with SessionLocal() as session:
        row = await BotRepository(session).get(bot_id)
    if row is None:
        await forget(bot_id)
        return None
    made = _made.get(bot_id)
    if made is not None and made.token == row.token:
        return made.bot
    async with _lock:
        made = _made.get(bot_id)
        if made is not None and made.token == row.token:
            return made.bot
        if made is not None:
            await _close(bot_id, made)
        opened = build(row.token)
        _made[bot_id] = Made(row.token, opened)
        logger.info("bot=%s api client opened", bot_id)
        return opened


async def _close(bot_id: int, made: Made) -> None:
    try:
        await made.bot.session.close()
    except Exception:
        logger.warning("bot=%s api client did not close cleanly", bot_id, exc_info=True)


async def forget(bot_id: int) -> None:
    async with _lock:
        made = _made.pop(bot_id, None)
    if made is not None:
        await _close(bot_id, made)
        logger.info("bot=%s api client closed", bot_id)


async def close_all() -> None:
    async with _lock:
        made = dict(_made)
        _made.clear()
    for bot_id, entry in made.items():
        await _close(bot_id, entry)
    if made:
        logger.info("closed %s api client(s)", len(made))
