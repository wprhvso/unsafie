import logging

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.config import Config

logger = logging.getLogger(__name__)


class ConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self) -> Config:
        config = await self.session.get(Config, 1)
        if config is None:
            config = Config(id=1, ratio=1.0, oauth_ratio=0.5)
            self.session.add(config)
            await self.session.commit()
            logger.info("config row created")
        return config

    async def set_ratios(self, ratio: float | None, oauth_ratio: float | None) -> Config:
        config = await self.get()
        old = (config.ratio, config.oauth_ratio)
        if ratio is not None:
            config.ratio = ratio
        if oauth_ratio is not None:
            config.oauth_ratio = oauth_ratio
        await self.session.commit()
        logger.info("config ratios %s -> %s", old, (config.ratio, config.oauth_ratio))
        return config
