from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.ci import (
    CiApiToken,
    CiJob,
    CiRun,
    CiRunMetric,
    CiSecret,
    CiWhitelist,
)


class CiRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_whitelisted(self, login: str | None) -> bool:
        if not login:
            return False
        stmt = select(CiWhitelist.github_login).where(func.lower(CiWhitelist.github_login) == login.lower())
        res = await self.session.scalar(stmt)
        return res is not None

    async def add_to_whitelist(self, login: str, added_by: str) -> CiWhitelist:
        clean = login.strip().lstrip("@").lower()
        stmt = insert(CiWhitelist).values(github_login=clean, added_by=added_by).on_conflict_do_nothing()
        await self.session.execute(stmt)
        await self.session.commit()
        return CiWhitelist(github_login=clean, added_by=added_by)

    async def remove_from_whitelist(self, login: str) -> bool:
        clean = login.strip().lstrip("@").lower()
        stmt = delete(CiWhitelist).where(func.lower(CiWhitelist.github_login) == clean)
        res = await self.session.execute(stmt)
        await self.session.commit()
        return (res.rowcount or 0) > 0

    async def list_whitelist(self) -> list[CiWhitelist]:
        stmt = select(CiWhitelist).order_by(CiWhitelist.created_at.desc())
        res = await self.session.scalars(stmt)
        return list(res)

    async def create_api_token(self, login: str, name: str, token_hash: str, prefix: str) -> CiApiToken:
        item = CiApiToken(github_login=login.lower(), name=name, token_hash=token_hash, token_prefix=prefix)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_api_token(self, token_hash: str) -> CiApiToken | None:
        stmt = select(CiApiToken).where(CiApiToken.token_hash == token_hash)
        item = await self.session.scalar(stmt)
        if item:
            item.last_used_at = datetime.now(UTC)
            await self.session.commit()
        return item

    async def list_api_tokens(self, login: str) -> list[CiApiToken]:
        stmt = select(CiApiToken).where(func.lower(CiApiToken.github_login) == login.lower()).order_by(CiApiToken.created_at.desc())
        res = await self.session.scalars(stmt)
        return list(res)

    async def delete_api_token(self, login: str, token_id: int) -> bool:
        stmt = delete(CiApiToken).where(CiApiToken.id == token_id, func.lower(CiApiToken.github_login) == login.lower())
        res = await self.session.execute(stmt)
        await self.session.commit()
        return (res.rowcount or 0) > 0

    async def get_secrets(self, repo_full_name: str) -> dict[str, str]:
        stmt = select(CiSecret).where(CiSecret.repo_full_name == repo_full_name)
        rows = await self.session.scalars(stmt)
        return {r.key: r.value for r in rows}

    async def list_secrets(self, repo_full_name: str) -> list[CiSecret]:
        stmt = select(CiSecret).where(CiSecret.repo_full_name == repo_full_name).order_by(CiSecret.key.asc())
        rows = await self.session.scalars(stmt)
        return list(rows)

    async def set_secret(self, repo_full_name: str, key: str, value: str, updated_by: str) -> None:
        stmt = insert(CiSecret).values(
            repo_full_name=repo_full_name,
            key=key,
            value=value,
            updated_by=updated_by,
        ).on_conflict_do_update(
            index_elements=["repo_full_name", "key"],
            set_={"value": value, "updated_by": updated_by, "updated_at": func.now()},
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def delete_secret(self, repo_full_name: str, key: str) -> bool:
        stmt = delete(CiSecret).where(CiSecret.repo_full_name == repo_full_name, CiSecret.key == key)
        res = await self.session.execute(stmt)
        await self.session.commit()
        return (res.rowcount or 0) > 0

    async def enqueue_run(
        self,
        *,
        installation_id: int,
        repo_full_name: str,
        commit_sha: str,
        ref: str,
        branch: str,
        is_default_branch: bool,
        sender: str | None = None,
        commit_message: str | None = None,
        trigger_event: str = "push",
    ) -> CiRun:
        run = CiRun(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            ref=ref,
            branch=branch,
            is_default_branch=is_default_branch,
            sender=sender,
            commit_message=commit_message,
            trigger_event=trigger_event,
            status="pending",
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def claim_next(self, worker_id: str, lease_seconds: int = 30) -> CiRun | None:
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        stmt = (
            select(CiRun)
            .where(CiRun.status == "pending")
            .order_by(CiRun.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        run = await self.session.scalar(stmt)
        if not run:
            return None
        run.status = "in_progress"
        run.started_at = now
        run.lease_worker_id = worker_id
        run.lease_until = lease_until
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def renew_lease(self, run_id: int, lease_seconds: int = 30) -> bool:
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        stmt = (
            update(CiRun)
            .where(CiRun.id == run_id, CiRun.status == "in_progress")
            .values(lease_until=lease_until, updated_at=now)
        )
        res = await self.session.execute(stmt)
        await self.session.commit()
        return (res.rowcount or 0) > 0

    async def set_check_run_id(self, run_id: int, check_run_id: int) -> None:
        stmt = update(CiRun).where(CiRun.id == run_id).values(check_run_id=check_run_id, updated_at=datetime.now(UTC))
        await self.session.execute(stmt)
        await self.session.commit()

    async def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        exit_code: int | None = None,
        error_message: str | None = None,
        current_stage: str | None = None,
        log_path: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        values = {
            "status": status,
            "completed_at": now,
            "exit_code": exit_code,
            "error_message": error_message,
            "current_stage": current_stage,
            "updated_at": now,
        }
        if log_path:
            values["log_path"] = log_path
        stmt = update(CiRun).where(CiRun.id == run_id).values(**values)
        await self.session.execute(stmt)
        await self.session.commit()

    async def find_stale_runs(self) -> list[CiRun]:
        now = datetime.now(UTC)
        stmt = select(CiRun).where(CiRun.status == "in_progress", CiRun.lease_until < now)
        res = await self.session.scalars(stmt)
        return list(res)

    async def get_run(self, run_id: int) -> CiRun | None:
        stmt = select(CiRun).where(CiRun.id == run_id)
        return await self.session.scalar(stmt)

    async def list_runs(self, repo_full_name: str | None = None, limit: int = 50, offset: int = 0) -> list[CiRun]:
        stmt = select(CiRun)
        if repo_full_name:
            stmt = stmt.where(CiRun.repo_full_name == repo_full_name)
        stmt = stmt.order_by(desc(CiRun.id)).offset(offset).limit(limit)
        res = await self.session.scalars(stmt)
        return list(res)

    async def record_metrics(self, run_id: int, cpu_percent: float, memory_rss_mb: float, rx_kbps: float, tx_kbps: float) -> None:
        item = CiRunMetric(
            run_id=run_id,
            cpu_percent=cpu_percent,
            memory_rss_mb=memory_rss_mb,
            network_rx_kbps=rx_kbps,
            network_tx_kbps=tx_kbps,
        )
        self.session.add(item)
        await self.session.commit()

    async def get_metrics(self, run_id: int) -> list[CiRunMetric]:
        stmt = select(CiRunMetric).where(CiRunMetric.run_id == run_id).order_by(CiRunMetric.recorded_at.asc())
        res = await self.session.scalars(stmt)
        return list(res)

    async def create_job(self, run_id: int, name: str, stage: str) -> CiJob:
        job = CiJob(run_id=run_id, name=name, stage=stage, status="pending")
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def list_jobs(self, run_id: int) -> list[CiJob]:
        stmt = select(CiJob).where(CiJob.run_id == run_id).order_by(CiJob.id.asc())
        res = await self.session.scalars(stmt)
        return list(res)

    async def get_job(self, run_id: int, name: str) -> CiJob | None:
        stmt = select(CiJob).where(CiJob.run_id == run_id, CiJob.name == name)
        return await self.session.scalar(stmt)

    async def set_job_check_run_id(self, job_id: int, check_run_id: int) -> None:
        stmt = update(CiJob).where(CiJob.id == job_id).values(check_run_id=check_run_id, updated_at=datetime.now(UTC))
        await self.session.execute(stmt)
        await self.session.commit()

    async def start_job(self, job_id: int) -> None:
        now = datetime.now(UTC)
        stmt = update(CiJob).where(CiJob.id == job_id).values(status="in_progress", started_at=now, updated_at=now)
        await self.session.execute(stmt)
        await self.session.commit()

    async def finish_job(
        self,
        job_id: int,
        *,
        status: str,
        exit_code: int | None = None,
        error_message: str | None = None,
        log_path: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        values = {
            "status": status,
            "completed_at": now,
            "exit_code": exit_code,
            "error_message": error_message,
            "updated_at": now,
        }
        if log_path:
            values["log_path"] = log_path
        stmt = update(CiJob).where(CiJob.id == job_id).values(**values)
        await self.session.execute(stmt)
        await self.session.commit()
