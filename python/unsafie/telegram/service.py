import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.bot import Bot
from unsafie.database.repositories.bot import BotRepository
from unsafie.telegram import bots, webhook

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
    await webhook.ensure_webhook(bot.id, token, force=True)
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
    await webhook.ensure_webhook(bot_id, token, force=True)
    return bot


async def delete(session: AsyncSession, bot_id: int) -> None:
    bot = await BotRepository(session).get(bot_id)
    if bot is None:
        raise BotNotFound
    token = bot.token
    if not await BotRepository(session).delete(bot_id):
        raise BotNotFound
    await bots.forget(bot_id)
    await webhook.delete_webhook(bot_id, token)


async def restart(session: AsyncSession, bot_id: int) -> Bot:
    bot = await BotRepository(session).get(bot_id)
    if bot is None:
        raise BotNotFound
    await webhook.ensure_webhook(bot_id, bot.token, force=True)
    return bot
