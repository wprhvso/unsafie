import logging

from unsafie.database import SessionLocal
from unsafie.database.repositories.delivery import DeliveryRepository
from unsafie.github.webhooks import router
from unsafie.loop import Loop
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class Worker(Loop):
    name = "webhook-worker"
    startup_delay = 5.0
    min_interval = 0.5

    @property
    def enabled(self) -> bool:
        return settings.runs_worker

    @property
    def interval(self) -> float:
        return settings.webhook_worker_interval

    async def tick(self) -> None:
        async with SessionLocal() as session:
            claimed = await DeliveryRepository(session).claim(
                settings.webhook_batch, settings.job_lease
            )
        if not claimed:
            return
        logger.info("claimed %s webhook deliver(ies)", len(claimed))
        for row in claimed:
            await router.process(row)


worker = Worker()
