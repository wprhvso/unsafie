import logging

from unsafie import telemetry
from unsafie.database import SessionLocal
from unsafie.database.repositories.delivery import DeliveryRepository
from unsafie.loop import Loop
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class CleanupLoop(Loop):
    name = "webhook-cleanup"
    startup_delay = 60.0

    @property
    def enabled(self) -> bool:
        return settings.runs_worker

    @property
    def interval(self) -> float:
        return float(settings.webhook_cleanup_interval)

    async def tick(self) -> None:
        with telemetry.muted():
            async with SessionLocal() as session:
                deliveries = await DeliveryRepository(session).purge(settings.webhook_keep_days)
        if deliveries:
            logger.info("cleanup removed deliveries=%s", deliveries)


cleanup = CleanupLoop()
