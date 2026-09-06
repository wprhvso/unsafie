import asyncio
import logging

from aiogram.types import Update

from unsafie.agent import runtime
from unsafie.database import SessionLocal
from unsafie.database.models.job import Job, JobKind, JobState
from unsafie.database.repositories.job import JobRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.loop import Loop
from unsafie.settings import settings
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)


class Executor(Loop):
    name = "executor"
    startup_delay = 4.0

    def __init__(self) -> None:
        super().__init__()
        self._running: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return settings.role in ("worker", "all")

    @property
    def interval(self) -> float:
        return settings.job_poll_interval

    @property
    def lanes(self) -> list[str]:
        return [settings.default_lane, "canary"]

    async def tick(self) -> None:
        while len(self._running) < settings.worker_concurrency:
            async with SessionLocal() as session:
                job = await JobRepository(session).claim(
                    settings.node_id, self.lanes, settings.job_lease, settings.release_sha
                )
            if job is None:
                return
            task = asyncio.create_task(self._run(job), name=f"job-{job.id}")
            self._running.add(task)
            task.add_done_callback(self._running.discard)

    async def _run(self, job: Job) -> None:
        hb = asyncio.create_task(self._heartbeat(job.id))
        try:
            if job.kind == JobKind.UPDATE:
                await self._run_update(job)
            else:
                logger.warning("job=%s unsupported kind=%s", job.id, job.kind)
            async with SessionLocal() as session:
                await JobRepository(session).finish(job.id, JobState.DONE)
        except Exception as e:
            logger.exception("job=%s failed", job.id)
            async with SessionLocal() as session:
                repo = JobRepository(session)
                if job.attempt >= settings.job_max_attempts:
                    await repo.finish(job.id, JobState.DEAD, str(e)[:500])
                else:
                    await repo.requeue(job.id, job.resume, str(e)[:500])
        finally:
            hb.cancel()

    async def _heartbeat(self, job_id: int) -> None:
        try:
            while True:
                await asyncio.sleep(settings.job_heartbeat)
                async with SessionLocal() as session:
                    await JobRepository(session).heartbeat(job_id, settings.job_lease)
        except asyncio.CancelledError:
            pass

    async def _run_update(self, job: Job) -> None:
        bot = manager.bot(job.bot_id)
        if bot is None:
            raise RuntimeError(f"bot {job.bot_id} not running")
        update = Update.model_validate(job.payload)
        async with SessionLocal() as session:
            stored = await UpdateRepository(session).save(
                bot_id=job.bot_id,
                update_id=update.update_id,
                chat_id=job.chat_id,
                message_id=(update.message.message_id if update.message else None),
                user_id=job.user_id,
                payload=job.payload,
            )
        if update.message is not None:
            await runtime.handle(update.message.as_(bot), job.bot_id, stored)
        elif update.callback_query is not None:
            q = update.callback_query
            if q.message is not None:
                await runtime.handle_callback(q.as_(bot), q.message.as_(bot), job.bot_id, stored)


executor = Executor()
