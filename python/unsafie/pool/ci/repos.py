from unsafie.log import get_logger
import re
from datetime import UTC, datetime

from sqlalchemy import select

from unsafie.database import SessionLocal
from unsafie.database.models.pool import PoolCiJob, PoolCiRepo
from unsafie.errors import OpsError
from unsafie.github import pat
from unsafie.github.client.base import GithubHTTP
from unsafie.github.errors import GithubError, NotFound, UserAuthRequired
from unsafie.settings import settings

logger = get_logger(__name__)

SLUG = re.compile(r"^[^/\s]+/[^/\s]+$")
LABEL = re.compile(r"^[a-zA-Z0-9][\w.-]{0,31}$")


class CiError(OpsError):
    pass


def check_slug(raw: str) -> str:
    slug = (raw or "").strip().strip("/")
    if slug.startswith("https://github.com/"):
        slug = slug.removeprefix("https://github.com/")
    if not SLUG.match(slug):
        msg = f"expected owner/name, got '{raw}'"
        raise CiError(msg)
    return slug


def check_label(raw: str | None) -> str:
    label = (raw or "pool").strip()
    if not LABEL.match(label):
        msg = "a label is 1-32 chars: letters, digits, dot, dash, underscore"
        raise CiError(msg)
    return label


async def token_for(user_id: int) -> str:
    try:
        account = await pat.require_account(user_id)
    except UserAuthRequired:
        msg = (
            "no github token. Give the bot one with /gh <token>; it needs "
            "Administration: read and write on the repository"
        )
        raise CiError(
            msg,
        ) from None
    if not account.token:
        msg = f"the account {account.login} has no token stored"
        raise CiError(msg)
    return account.token


async def preflight(slug: str, token: str) -> dict:
    http = GithubHTTP(token)
    try:
        repo = await http.request("GET", f"/repos/{slug}")
    except NotFound:
        msg = f"{slug} is not visible to this token: no repository or no access"
        raise CiError(msg) from None
    except GithubError as refused:
        msg = f"{slug}: {refused}"
        raise CiError(msg) from None
    try:
        await http.request("GET", f"/repos/{slug}/actions/runners", params={"per_page": 1})
    except GithubError:
        msg = (
            f"{slug}: the token cannot administer this repository. A fine-grained token needs "
            "Administration: read and write, a classic one needs the repo scope"
        )
        raise CiError(
            msg,
        ) from None
    return repo


async def add(
    user_id: int,
    raw_slug: str,
    label: str | None = None,
    jobs: int | None = None,
    idle: int | None = None,
    lifetime: int | None = None,
) -> PoolCiRepo:
    slug = check_slug(raw_slug)
    mark = check_label(label)
    token = await token_for(user_id)
    await preflight(slug, token)
    async with SessionLocal() as session:
        row = await session.scalar(
            select(PoolCiRepo).where(PoolCiRepo.user_id == user_id, PoolCiRepo.slug == slug),
        )
        if row is None:
            row = PoolCiRepo(user_id=user_id, slug=slug)
            session.add(row)
        row.label = mark
        row.jobs = max(1, min(jobs or settings.pool_ci_jobs, settings.pool_ci_max_jobs))
        row.idle = idle or int(settings.pool_ci_idle)
        row.lifetime = lifetime or int(settings.pool_ci_lifetime)
        row.enabled = True
        row.state = "new"
        row.last_error = None
        await session.commit()
        await session.refresh(row)
    logger.info("pool ci %s wired by user=%s label=%s", slug, user_id, mark)
    return row


async def remove(user_id: int, raw_slug: str) -> PoolCiRepo | None:
    slug = check_slug(raw_slug)
    async with SessionLocal() as session:
        row = await session.scalar(
            select(PoolCiRepo).where(PoolCiRepo.user_id == user_id, PoolCiRepo.slug == slug),
        )
        if row is None:
            return None
        await session.delete(row)
        await session.commit()
    logger.info("pool ci %s dropped by user=%s", slug, user_id)
    return row


async def of_user(user_id: int) -> list[PoolCiRepo]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(PoolCiRepo).where(PoolCiRepo.user_id == user_id).order_by(PoolCiRepo.id),
        )
        return list(rows)


async def get(user_id: int, raw_slug: str) -> PoolCiRepo | None:
    slug = check_slug(raw_slug)
    async with SessionLocal() as session:
        return await session.scalar(
            select(PoolCiRepo).where(PoolCiRepo.user_id == user_id, PoolCiRepo.slug == slug),
        )


async def enabled_repos() -> list[PoolCiRepo]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(PoolCiRepo).where(PoolCiRepo.enabled.is_(True)).order_by(PoolCiRepo.id),
        )
        return list(rows)


async def enable(user_id: int | None, raw_slug: str, on: bool) -> PoolCiRepo | None:
    slug = check_slug(raw_slug)
    async with SessionLocal() as session:
        query = select(PoolCiRepo).where(PoolCiRepo.slug == slug)
        if user_id is not None:
            query = query.where(PoolCiRepo.user_id == user_id)
        row = await session.scalar(query)
        if row is None:
            return None
        row.enabled = on
        row.state = "ready" if on else "paused"
        await session.commit()
        await session.refresh(row)
    return row


async def note(repo_id: int, state: str, error: str | None = None, scale_set: int | None = None) -> None:
    async with SessionLocal() as session:
        row = await session.get(PoolCiRepo, repo_id)
        if row is None:
            return
        row.state = state
        row.last_error = error
        if scale_set is not None:
            row.scale_set_id = scale_set
        row.reconciled_at = datetime.now(UTC)
        await session.commit()


async def start_job(repo_id: int, machine: str, runner: str | None) -> PoolCiJob:
    async with SessionLocal() as session:
        row = PoolCiJob(repo_id=repo_id, machine=machine, job=runner, status="assigned")
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def finish_job(job_id: int, status: str, result: str | None) -> None:
    async with SessionLocal() as session:
        row = await session.get(PoolCiJob, job_id)
        if row is None:
            return
        row.status = status
        row.result = result
        row.finished_at = datetime.now(UTC)
        await session.commit()


async def running_jobs(repo_id: int) -> list[PoolCiJob]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(PoolCiJob).where(
                PoolCiJob.repo_id == repo_id, PoolCiJob.finished_at.is_(None),
            ),
        )
        return list(rows)


async def close_orphans() -> int:
    from unsafie.pool import registry

    async with SessionLocal() as session:
        rows = list(
            await session.scalars(select(PoolCiJob).where(PoolCiJob.finished_at.is_(None))),
        )
        closed = 0
        for row in rows:
            if row.machine and await registry.alive(row.machine):
                continue
            row.status = "lost"
            row.result = "the machine went away"
            row.finished_at = datetime.now(UTC)
            closed += 1
        if closed:
            await session.commit()
            logger.info("pool ci: %s runner(s) written off, their machines are gone", closed)
        return closed


async def recent_jobs(repo_id: int, limit: int = 50) -> list[PoolCiJob]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(PoolCiJob)
            .where(PoolCiJob.repo_id == repo_id)
            .order_by(PoolCiJob.started_at.desc())
            .limit(limit),
        )
        return list(rows)


def snippet(row: PoolCiRepo) -> str:
    return "\n".join(
        [
            "jobs:",
            "  build:",
            f"    runs-on: {row.label}",
            "",
            f"The label is the name of the scale set in {row.slug}.",
            "Arrays in runs-on do not work: pass the label as a plain string.",
        ],
    )
