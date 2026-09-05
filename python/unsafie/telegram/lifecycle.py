import logging

from unsafie.database import SessionLocal
from unsafie.database.repositories.bot import BotRepository
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)


async def start_all() -> None:
    async with SessionLocal() as session:
        records = await BotRepository(session).all()
    if not records:
        logger.info("bots start: none in database")
        return
    for record in records:
        try:
            await manager.start(record.id, record.token)
        except Exception:
            logger.exception("bot=%s start failed", record.id)
    logger.info("bots start done running=%s", manager.running_ids())


async def stop_all() -> None:
    await manager.stop_all()
    logger.info("bots stop done")
