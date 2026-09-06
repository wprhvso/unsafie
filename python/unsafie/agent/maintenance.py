import logging

from unsafie.database import SessionLocal
from unsafie.database.repositories.job import JobRepository
from unsafie.loop import Loop

logger = logging.getLogger(__name__)


class JobReaper(Loop):
    name = "job-reaper"
    interval = 15.0
    startup_delay = 15.0

    async def tick(self) -> None:
        async with SessionLocal() as session:
            reaped = await JobRepository(session).reap_expired()
        if reaped:
            logger.info("reaped %s expired job lease(s)", reaped)


reaper = JobReaper()
