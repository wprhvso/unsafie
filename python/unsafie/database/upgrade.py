import asyncio
import logging
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from unsafie.settings import settings

logger = logging.getLogger(__name__)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


async def ensure_database() -> None:
    url = make_url(settings.database_url)
    name = url.database
    engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            if exists:
                logger.debug("database %s exists", name)
                return
            quoted = name.replace('"', '""')
            await conn.execute(text(f'CREATE DATABASE "{quoted}"'))
            logger.info("database %s created", name)
    finally:
        await engine.dispose()


def _upgrade() -> None:
    logger.info("alembic upgrade head ini=%s", ALEMBIC_INI)
    started = time.perf_counter()
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    logger.info("alembic upgrade done in %.1fms", (time.perf_counter() - started) * 1000)


MIGRATE_LOCK = 8712361


async def upgrade() -> None:
    await ensure_database()
    from unsafie.database import SessionLocal

    async with SessionLocal() as session:
        await session.execute(text("SELECT pg_advisory_lock(:k)").bindparams(k=MIGRATE_LOCK))
        try:
            await asyncio.to_thread(_upgrade)
        finally:
            await session.execute(text("SELECT pg_advisory_unlock(:k)").bindparams(k=MIGRATE_LOCK))
            await session.commit()
