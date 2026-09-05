import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.bot import Bot

logger = logging.getLogger(__name__)


class BotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, token: str) -> Bot:
        bot = Bot(token=token)
        self.session.add(bot)
        await self.session.commit()
        logger.info("bot=%s row created", bot.id)
        return bot

    async def get(self, bot_id: int) -> Bot | None:
        return await self.session.get(Bot, bot_id)

    async def all(self) -> list[Bot]:
        return list(await self.session.scalars(select(Bot).order_by(Bot.id)))

    async def update_token(self, bot_id: int, token: str) -> Bot | None:
        bot = await self.session.get(Bot, bot_id)
        if bot is None:
            return None
        bot.token = token
        await self.session.commit()
        logger.info("bot=%s token updated", bot_id)
        return bot

    async def delete(self, bot_id: int) -> bool:
        bot = await self.session.get(Bot, bot_id)
        if bot is None:
            return False
        await self.session.delete(bot)
        await self.session.commit()
        logger.info("bot=%s row deleted", bot_id)
        return True
