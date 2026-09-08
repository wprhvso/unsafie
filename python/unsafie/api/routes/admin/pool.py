from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from unsafie.api.schemas.common import Ok
from unsafie.database import SessionLocal
from unsafie.database.models.pool import PoolCiRepo, PoolDonor, PoolMachine, PoolUsage
from unsafie.database.models.user import User
from unsafie.errors import OpsError
from unsafie.pool import donors, leases, registry
from unsafie.pool.ci import repos as ci_repos

router = APIRouter(prefix="/pool", tags=["pool"])


class DonorIn(BaseModel):
    token: str
    jobs: int = 20
    label: str | None = None


class QuotaIn(BaseModel):
    machines: int | None = None
    background: int | None = None
    minutes: int | None = None
    machines_day: int | None = None
    priority: int | None = None
    blocked: bool | None = None


def _donor(row: PoolDonor) -> dict:
    return {
        "id": row.id,
        "login": row.login,
        "label": row.label,
        "repo": row.repo,
        "workflow": row.workflow,
        "jobs": row.jobs,
        "enabled": row.enabled,
        "state": row.state,
        "last_error": row.last_error,
        "created_at": row.created_at,
        "reconciled_at": row.reconciled_at,
    }


def _machine(row: PoolMachine) -> dict:
    return {
        "name": row.name,
        "alias": row.alias,
        "donor_id": row.donor_id,
        "run_id": row.run_id,
        "state": row.state,
        "user_id": row.user_id,
        "chat_id": row.chat_id,
        "boot_seconds": row.boot_seconds,
        "started_at": row.started_at,
        "leased_at": row.leased_at,
        "facts": row.facts,
    }


@router.get("/donors")
async def list_donors() -> dict:
    return {"donors": [_donor(row) for row in await donors.all_donors()]}


@router.post("/donors")
async def add_donor(body: DonorIn) -> dict:
    try:
        donor, worker_token = await donors.add(body.token, body.jobs, body.label)
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    return {
        "donor": _donor(donor),
        "worker_token": worker_token,
        "next": "call bootstrap to create the repository, push the workflow and seal the secrets",
    }


@router.post("/donors/{login}/bootstrap")
async def bootstrap_donor(login: str) -> dict:
    try:
        return await donors.bootstrap(login)
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None


@router.post("/donors/{login}/rotate")
async def rotate_donor(login: str) -> dict:
    try:
        token = await donors.rotate(login)
    except OpsError as refused:
        raise HTTPException(404, str(refused)) from None
    return {"worker_token": token, "next": "bootstrap the donor so its jobs get the new token"}


@router.post("/donors/{login}/enable", response_model=Ok)
async def enable_donor(login: str, on: bool = True):
    if not await donors.enable(login, on):
        raise HTTPException(404, "no such donor")
    return Ok(detail="enabled" if on else "disabled")


@router.delete("/donors/{login}", response_model=Ok)
async def drop_donor(login: str):
    if not await donors.remove(login):
        raise HTTPException(404, "no such donor")
    return Ok(detail="removed")


@router.get("/machines")
async def list_machines() -> dict:
    rows = await registry.live()
    return {"machines": [_machine(row) for row in rows], "capacity": await registry.counted()}


@router.post("/machines/recycle", response_model=Ok)
async def recycle_all():
    names = [row.name for row in await registry.live()]
    for name in names:
        await leases.destroy(name, "pool wiped by the operator")
    return Ok(detail=f"destroyed {len(names)}")


@router.post("/machines/{name}/recycle", response_model=Ok)
async def recycle(name: str):
    if await registry.machine(name) is None:
        raise HTTPException(404, "no such machine")
    await leases.destroy(name, "recycled by the operator")
    return Ok(detail="destroyed")


def _ci(row: PoolCiRepo) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
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


@router.get("/ci")
async def list_ci() -> dict:
    async with SessionLocal() as session:
        rows = await session.scalars(select(PoolCiRepo).order_by(PoolCiRepo.id))
        wired = list(rows)
    live: dict[int, int] = {}
    for row in wired:
        live[row.id] = len(await ci_repos.running_jobs(row.id))
    return {"repos": [{**_ci(row), "runners": live.get(row.id, 0)} for row in wired]}


@router.post("/ci/{owner}/{name}/enable", response_model=Ok)
async def enable_ci(owner: str, name: str, on: bool = True):
    row = await ci_repos.enable(None, f"{owner}/{name}", on)
    if row is None:
        raise HTTPException(404, "this repository is not wired to the pool")
    return Ok(detail="running" if on else "paused")


@router.get("/users")
async def list_users() -> dict:
    today = datetime.now(UTC).date()
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(User).order_by(User.id)))
        usage = {
            row.user_id: row
            for row in await session.scalars(select(PoolUsage).where(PoolUsage.day == today))
        }
    machines = await registry.live()
    held: dict[int, int] = {}
    for machine in machines:
        if machine.user_id is not None:
            held[machine.user_id] = held.get(machine.user_id, 0) + 1
    out = []
    for user in rows:
        today_usage = usage.get(user.id)
        if not held.get(user.id) and today_usage is None and user.pool_priority == 0:
            continue
        out.append(
            {
                "user_id": user.id,
                "machines_now": held.get(user.id, 0),
                "max_machines": user.pool_max_machines,
                "max_background": user.pool_max_background,
                "max_minutes_day": user.pool_max_minutes_day,
                "max_machines_day": user.pool_max_machines_day,
                "priority": user.pool_priority,
                "blocked": user.pool_blocked,
                "minutes_today": round((today_usage.machine_seconds if today_usage else 0) / 60, 1),
                "commands_today": today_usage.commands if today_usage else 0,
            }
        )
    return {"users": out}


@router.post("/users/{user_id}/quota")
async def set_quota(user_id: int, body: QuotaIn) -> dict:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(404, "no such user")
        if body.machines is not None:
            user.pool_max_machines = body.machines
        if body.background is not None:
            user.pool_max_background = body.background
        if body.minutes is not None:
            user.pool_max_minutes_day = body.minutes
        if body.machines_day is not None:
            user.pool_max_machines_day = body.machines_day
        if body.priority is not None:
            user.pool_priority = body.priority
        if body.blocked is not None:
            user.pool_blocked = body.blocked
        await session.commit()
        return {
            "user_id": user.id,
            "max_machines": user.pool_max_machines,
            "max_background": user.pool_max_background,
            "max_minutes_day": user.pool_max_minutes_day,
            "max_machines_day": user.pool_max_machines_day,
            "priority": user.pool_priority,
            "blocked": user.pool_blocked,
        }


@router.get("/capacity")
async def capacity() -> dict:
    counts = await registry.counted()
    rows = await donors.all_donors(enabled_only=True)
    return {
        "machines": counts,
        "idle": await registry.idle_count(),
        "donors": len(rows),
        "target_jobs": sum(row.jobs for row in rows),
    }
