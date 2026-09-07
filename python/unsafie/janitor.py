import logging

from unsafie import events
from unsafie.database import SessionLocal
from unsafie.database.repositories.transcript import TranscriptRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.loop import Loop
from unsafie.settings import settings

logger = logging.getLogger(__name__)


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
        await self._purge()

    async def _reap(self) -> None:
        async with SessionLocal() as session:
            reaped = await TurnRepository(session).reap_stale(settings.turn_stale_after)
        for turn in reaped:
            logger.warning(
                "turn=%s reaped: instance %s went silent for more than %ss",
                turn.id,
                turn.instance_id,
                settings.turn_stale_after,
            )
            events.publish(
                "turn.reaped",
                turn_id=str(turn.id),
                bot_id=turn.bot_id,
                chat_id=turn.chat_id,
                user_id=turn.user_id,
                instance=turn.instance_id,
            )

    async def _purge(self) -> None:
        async with SessionLocal() as session:
            gone = await TranscriptRepository(session).purge(settings.transcript_keep_days)
        if gone:
            logger.info(
                "purged %s transcript(s) untouched for %s days",
                gone,
                settings.transcript_keep_days,
            )


janitor = Janitor()
