import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.bot import Bot
from unsafie.database.repositories.bot import BotRepository
from unsafie.telegram import bots, poller

logger = logging.getLogger(__name__)


class BotNotFound(Exception):
    pass


class BotTokenTaken(Exception):
    pass


def mask(token: str) -> str:
    return f"{token[:6]}…{token[-4:]}" if len(token) > 12 else "***"


async def create(session: AsyncSession, token: str) -> Bot:
    me = await bots.identify(token)
    try:
        bot = await BotRepository(session).create(token, me.id, me.username or "")
    except IntegrityError:
        await session.rollback()
        raise BotTokenTaken from None
    await poller.reconcile()
    return bot


async def update_token(session: AsyncSession, bot_id: int, token: str) -> Bot:
    me = await bots.identify(token)
    try:
        bot = await BotRepository(session).update_token(bot_id, token, me.id, me.username or "")
    except IntegrityError:
        await session.rollback()
        raise BotTokenTaken from None
    if bot is None:
        raise BotNotFound
    await bots.forget(bot_id)
    await poller.reconcile()
    return bot


async def delete(session: AsyncSession, bot_id: int) -> None:
    if not await BotRepository(session).delete(bot_id):
        raise BotNotFound
    await bots.forget(bot_id)
    await poller.reconcile()


async def restart(session: AsyncSession, bot_id: int) -> Bot:
    bot = await BotRepository(session).get(bot_id)
    if bot is None:
        raise BotNotFound
    await poller.request_restart(bot_id)
    await poller.reconcile()
    return bot
