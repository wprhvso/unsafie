import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.bot import Bot

logger = logging.getLogger(__name__)


class BotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, token: str, tg_id: int | None, username: str | None) -> Bot:
        bot = Bot(token=token, tg_id=tg_id, username=username)
        self.session.add(bot)
        await self.session.commit()
        logger.info("bot=%s row created for @%s", bot.id, username)
        return bot

    async def get(self, bot_id: int) -> Bot | None:
        return await self.session.get(Bot, bot_id)

    async def all(self) -> list[Bot]:
        return list(await self.session.scalars(select(Bot).order_by(Bot.id)))

    async def ids(self) -> list[int]:
        return list(await self.session.scalars(select(Bot.id).order_by(Bot.id)))

    async def update_token(self, bot_id: int, token: str, tg_id: int, username: str) -> Bot | None:
        bot = await self.session.get(Bot, bot_id)
        if bot is None:
            return None
        bot.token = token
        bot.tg_id = tg_id
        bot.username = username
        await self.session.commit()
        logger.info("bot=%s token updated, now @%s", bot_id, username)
        return bot

    async def set_identity(self, bot_id: int, tg_id: int, username: str) -> None:
        bot = await self.session.get(Bot, bot_id)
        if bot is None or (bot.tg_id == tg_id and bot.username == username):
            return
        bot.tg_id = tg_id
        bot.username = username
        await self.session.commit()
        logger.info("bot=%s identity refreshed: @%s (tg_id=%s)", bot_id, username, tg_id)

    async def delete(self, bot_id: int) -> bool:
        bot = await self.session.get(Bot, bot_id)
        if bot is None:
            return False
        await self.session.delete(bot)
        await self.session.commit()
        logger.info("bot=%s row deleted", bot_id)
        return True
