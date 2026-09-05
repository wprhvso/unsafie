import logging

from unsafie.database import SessionLocal
from unsafie.database.repositories.delivery import DeliveryRepository
from unsafie.database.repositories.oauth_state import OAuthStateRepository
from unsafie.loop import Loop
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class CleanupLoop(Loop):
    name = "webhook-cleanup"
    startup_delay = 60.0

    @property
    def interval(self) -> float:
        return float(settings.webhook_cleanup_interval)

    async def tick(self) -> None:
        async with SessionLocal() as session:
            deliveries = await DeliveryRepository(session).purge(settings.webhook_keep_days)
            states = await OAuthStateRepository(session).purge()
        if deliveries or states:
            logger.info("cleanup removed deliveries=%s oauth_states=%s", deliveries, states)


cleanup = CleanupLoop()
