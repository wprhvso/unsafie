import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.job import Job, JobState

logger = logging.getLogger(__name__)


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(
        self,
        *,
        kind: str,
        bot_id: int,
        chat_id: int,
        user_id: int,
        lane: str,
        payload: dict[str, Any],
        update_id: int | None = None,
        priority: int = 100,
    ) -> int | None:
        stmt = (
            insert(Job)
            .values(
                kind=kind,
                bot_id=bot_id,
                chat_id=chat_id,
                user_id=user_id,
                lane=lane,
                payload=payload,
                update_id=update_id,
                priority=priority,
            )
            .on_conflict_do_nothing(index_elements=["bot_id", "update_id"])
            .returning(Job.id)
        )
        job_id = await self.session.scalar(stmt)
        await self.session.commit()
        if job_id is not None:
            await self.session.execute(text("NOTIFY unsafie_jobs, :lane").bindparams(lane=lane))
            await self.session.commit()
        return int(job_id) if job_id is not None else None

    async def claim(self, worker: str, lanes: list[str], lease: int, release_sha: str) -> Job | None:
        row = await self.session.execute(
            text(
                """
                UPDATE jobs SET state='running', worker=:worker, release_sha=:sha,
                    attempt=attempt+1, lease_until=now() + (:lease || ' seconds')::interval
                WHERE id = (
                    SELECT j.id FROM jobs j
                    WHERE j.state='ready' AND j.lane = ANY(:lanes) AND j.run_after <= now()
                      AND NOT EXISTS (
                        SELECT 1 FROM jobs r
                        WHERE r.chat_id = j.chat_id AND r.state='running')
                    ORDER BY j.priority, j.id
                    FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING id
                """
            ).bindparams(worker=worker, sha=release_sha, lease=str(lease), lanes=lanes)
        )
        job_id = row.scalar()
        await self.session.commit()
        if job_id is None:
            return None
        return await self.session.get(Job, int(job_id))

    async def heartbeat(self, job_id: int, lease: int) -> None:
        await self.session.execute(
            text(
                "UPDATE jobs SET lease_until = now() + (:lease || ' seconds')::interval "
                "WHERE id=:id AND state='running'"
            ).bindparams(lease=str(lease), id=job_id)
        )
        await self.session.commit()

    async def finish(self, job_id: int, state: JobState, note: str | None = None) -> None:
        job = await self.session.get(Job, job_id)
        if job is None:
            return
        job.state = state
        job.note = note
        job.lease_until = None
        await self.session.commit()

    async def requeue(self, job_id: int, resume: str | None, note: str | None) -> None:
        job = await self.session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.READY
        job.resume = resume
        job.note = note
        job.worker = None
        job.lease_until = None
        job.run_after = datetime.now(UTC)
        await self.session.commit()

    async def reap_expired(self) -> int:
        result = await self.session.execute(
            text(
                """
                UPDATE jobs SET state = CASE WHEN attempt >= :max THEN 'dead' ELSE 'ready' END,
                    worker=NULL, lease_until=NULL,
                    run_after = now() + (least(attempt, 5) || ' seconds')::interval
                WHERE state='running' AND lease_until < now()
                """
            ).bindparams(max=6)
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def bind_turn(self, job_id: int, turn_id: UUID) -> None:
        job = await self.session.get(Job, job_id)
        if job is not None:
            job.turn_id = turn_id
            await self.session.commit()

    async def stale_running(self, older_than: timedelta) -> int:
        cutoff = datetime.now(UTC) - older_than
        result = await self.session.execute(
            text(
                "UPDATE jobs SET state='ready', worker=NULL, lease_until=NULL "
                "WHERE state='running' AND (lease_until IS NULL OR lease_until < :cutoff)"
            ).bindparams(cutoff=cutoff)
        )
        await self.session.commit()
        return int(result.rowcount or 0)
