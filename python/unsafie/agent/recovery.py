import asyncio
import logging
from uuid import UUID

from unsafie.database import SessionLocal
from unsafie.database.repositories.turn import TurnRepository
from unsafie.loop import Loop
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class RecoverySupervisor(Loop):
    name = "recovery-supervisor"
    interval = 15.0
    startup_delay = 1.0

    @property
    def enabled(self) -> bool:
        return settings.runs_worker

    async def startup_sweep(self) -> list[UUID]:
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            stale = await repo.find_stale_running(threshold_seconds=settings.turn_heartbeat * 2)
        recovered: list[UUID] = []
        for turn in stale:
            claimed = await self.recover(turn.id)
            if claimed:
                recovered.append(turn.id)
        return recovered

    async def tick(self) -> None:
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            stale = await repo.find_stale_running(threshold_seconds=settings.turn_heartbeat * 2)
        for turn in stale:
            await self.recover(turn.id)

    async def recover(self, turn_id: UUID) -> bool:
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            turn = await repo.claim_for_recovery(
                turn_id=turn_id,
                instance_id=settings.instance_id,
                max_recoveries=3,
            )
        if turn is None:
            return False

        logger.info("recovering turn=%s attempts=%s", turn.id, turn.recovery_attempts)
        from unsafie.agent.runtime import resume_turn

        asyncio.create_task(resume_turn(turn.id), name=f"resume:{turn.id}")
        return True


recovery_supervisor = RecoverySupervisor()
