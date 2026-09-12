from unsafie.log import get_logger

from unsafie import events, telemetry
from unsafie.agent import live
from unsafie.database import SessionLocal
from unsafie.database.models.turn import TurnStatus
from unsafie.database.repositories.delivery import DeliveryRepository
from unsafie.database.repositories.segment import SegmentRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.loop import Loop
from unsafie.settings import settings

logger = get_logger(__name__)


class Janitor(Loop):
    name = "janitor"
    startup_delay = 15.0

    @property
    def enabled(self) -> bool:
        return settings.runs_worker

    @property
    def interval(self) -> float:
        return settings.janitor_interval

    async def tick(self) -> None:
        await self._reap()
        with telemetry.muted():
            await self._purge()

    async def _reap(self) -> None:
        async with SessionLocal() as session:
            reaped = await TurnRepository(session).reap_stale(settings.turn_stale_after * 2)
        for turn in reaped:
            logger.warning(
                "turn=%s reaped: instance %s went silent for more than %ss",
                turn.id,
                turn.instance_id,
                settings.turn_stale_after * 2,
            )
            events.publish(
                "turn.reaped",
                turn_id=str(turn.id),
                root_id=str(turn.root_id),
                bot_id=turn.bot_id,
                chat_id=turn.chat_id,
                user_id=turn.user_id,
                instance=turn.instance_id,
            )
            await live.seal(
                turn.id,
                status=str(TurnStatus.FAILED),
                note=f"instance {turn.instance_id or 'unknown'} stopped beating",
            )

    async def _purge(self) -> None:
        async with SessionLocal() as session:
            segments = await SegmentRepository(session).purge(settings.history_keep_days)
            deliveries = await DeliveryRepository(session).purge(settings.webhook_keep_days)
        if segments or deliveries:
            logger.info("purged segments=%s deliveries=%s", segments, deliveries)


janitor = Janitor()
