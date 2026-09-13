import asyncio
import os

from unsafie.database import SessionLocal
from unsafie.database.repositories.ci import CiRepository
from unsafie.github.ci import runner
from unsafie.github.ci.service import ci_event
from unsafie.log import get_logger
from unsafie.loop import Loop
from unsafie.settings import settings

logger = get_logger(__name__)

class CiWorker(Loop):
    name = "ci-worker"
    startup_delay = 2.0
    min_interval = 0.5

    @property
    def enabled(self) -> bool:
        return settings.runs_worker

    @property
    def interval(self) -> float:
        return 1.0

    async def tick(self) -> None:
        worker_id = f"{settings.instance_id}:{os.getpid()}"
        async with SessionLocal() as session:
            run = await CiRepository(session).claim_next(worker_id, lease_seconds=30)

        if not run:
            try:
                await asyncio.wait_for(ci_event.wait(), timeout=3.0)
                ci_event.clear()
            except TimeoutError:
                pass
            return

        logger.info("claimed ci run %s for %s", run.id, run.repo_full_name)
        try:
            await runner.execute_run(run.id)
        except Exception:
            logger.exception("unhandled error executing ci run %s", run.id)

ci_worker = CiWorker()
