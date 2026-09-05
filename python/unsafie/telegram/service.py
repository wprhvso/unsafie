import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.bot import Bot
from unsafie.database.repositories.bot import BotRepository
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)


class BotNotFound(Exception):
    pass


class BotTokenTaken(Exception):
    pass


def mask(token: str) -> str:
    return f"{token[:6]}…{token[-4:]}" if len(token) > 12 else "***"


async def create(session: AsyncSession, token: str) -> Bot:
    try:
        bot = await BotRepository(session).create(token)
    except IntegrityError:
        await session.rollback()
        raise BotTokenTaken from None
    await manager.start(bot.id, bot.token)
    return bot


async def update_token(session: AsyncSession, bot_id: int, token: str) -> Bot:
    try:
        bot = await BotRepository(session).update_token(bot_id, token)
    except IntegrityError:
        await session.rollback()
        raise BotTokenTaken from None
    if bot is None:
        raise BotNotFound
    await manager.restart(bot.id, bot.token)
    return bot


async def delete(session: AsyncSession, bot_id: int) -> None:
    if not await BotRepository(session).delete(bot_id):
        raise BotNotFound
    await manager.stop(bot_id)


async def restart(session: AsyncSession, bot_id: int) -> Bot:
    bot = await BotRepository(session).get(bot_id)
    if bot is None:
        raise BotNotFound
    await manager.restart(bot.id, bot.token)
    return bot
