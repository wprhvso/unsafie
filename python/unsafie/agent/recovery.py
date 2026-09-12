import asyncio
from unsafie.log import get_logger
from uuid import UUID

from unsafie.database import SessionLocal
from unsafie.database.repositories.turn import TurnRepository
from unsafie.loop import Loop
from unsafie.settings import settings

logger = get_logger(__name__)

_RECOVERY_TASKS: set[asyncio.Task] = set()


class RecoverySupervisor(Loop):
    name = "recovery-supervisor"
    interval = 15.0
    startup_delay = 1.0

    @property
    def enabled(self) -> bool:
        return settings.runs_worker or settings.runs_web

    async def startup_sweep(self) -> list[UUID]:
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            resumable = await repo.find_resumable(stale_after=settings.turn_stale_after, limit=50)
        recovered: list[UUID] = []
        for turn in resumable:
            claimed = await self.recover(turn.id)
            if claimed:
                recovered.append(turn.id)
        return recovered

    async def tick(self) -> None:
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            stale = await repo.find_stale_running(threshold_seconds=settings.turn_stale_after)
        for turn in stale:
            await self.recover(turn.id)

    async def recover(self, turn_id: UUID) -> bool:
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            turn = await repo.claim_for_recovery(
                turn_id=turn_id,
                instance_id=settings.instance_id,
                max_recoveries=3,
                stale_after=settings.turn_stale_after,
            )
        if turn is None:
            return False

        logger.info("recovering turn=%s attempts=%s", turn.id, turn.recovery_attempts)
        from unsafie.agent.runtime import resume_turn

        task = asyncio.create_task(resume_turn(turn.id), name=f"resume:{turn.id}")
        _RECOVERY_TASKS.add(task)
        task.add_done_callback(_RECOVERY_TASKS.discard)
        return True


recovery_supervisor = RecoverySupervisor()
