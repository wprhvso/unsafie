import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from unsafie.api.routes.cli.deps import Github
from unsafie.database.models.pool import PoolCiJob, PoolCiRepo
from unsafie.errors import OpsError
from unsafie.pool import registry
from unsafie.pool.ci import repos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ci", tags=["cli"])


class Wire(BaseModel):
    repo: str
    label: str | None = None
    jobs: int | None = None
    idle: int | None = None
    lifetime: int | None = None


def _view(row: PoolCiRepo) -> dict:
    return {
        "repo": row.slug,
        "label": row.label,
        "jobs": row.jobs,
        "idle": row.idle,
        "lifetime": row.lifetime,
        "enabled": row.enabled,
        "state": row.state,
        "last_error": row.last_error,
        "scale_set": row.scale_set_id,
        "reconciled_at": row.reconciled_at,
    }


def _job(row: PoolCiJob) -> dict:
    return {
        "runner": row.job,
        "machine": row.machine,
        "status": row.status,
        "result": row.result,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


async def _mine(who: Github, slug: str) -> PoolCiRepo:
    try:
        row = await repos.get(who.user_id, slug)
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    if row is None:
        raise HTTPException(404, f"{slug} is not wired to the pool")
    return row


@router.post("")
async def add(body: Wire, who: Github) -> dict:
    try:
        row = await repos.add(
            who.user_id, body.repo, body.label, body.jobs, body.idle, body.lifetime,
        )
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    return {"repo": _view(row), "snippet": repos.snippet(row)}


@router.get("")
async def listing(who: Github) -> dict:
    rows = await repos.of_user(who.user_id)
    return {"repos": [_view(row) for row in rows]}


@router.get("/{owner}/{name}")
async def status(owner: str, name: str, who: Github) -> dict:
    row = await _mine(who, f"{owner}/{name}")
    running = await repos.running_jobs(row.id)
    recent = await repos.recent_jobs(row.id, 10)
    return {
        "repo": _view(row),
        "runners": [_job(job) for job in running],
        "recent": [_job(job) for job in recent],
        "capacity": await registry.counted(),
        "snippet": repos.snippet(row),
    }


@router.get("/{owner}/{name}/jobs")
async def jobs(owner: str, name: str, who: Github, limit: int = 50) -> dict:
    row = await _mine(who, f"{owner}/{name}")
    return {"jobs": [_job(job) for job in await repos.recent_jobs(row.id, max(1, min(limit, 200)))]}


@router.get("/{owner}/{name}/snippet")
async def snippet(owner: str, name: str, who: Github) -> dict:
    row = await _mine(who, f"{owner}/{name}")
    return {"repo": row.slug, "label": row.label, "snippet": repos.snippet(row)}


@router.delete("/{owner}/{name}")
async def remove(owner: str, name: str, who: Github) -> dict:
    row = await _mine(who, f"{owner}/{name}")
    await repos.remove(who.user_id, row.slug)
    return {"repo": row.slug, "removed": True}
