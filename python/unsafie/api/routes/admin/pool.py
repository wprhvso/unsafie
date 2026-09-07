from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from unsafie.api.schemas.common import Ok
from unsafie.database.models.pool import PoolDonor, PoolMachine
from unsafie.errors import OpsError
from unsafie.pool import donors, leases, registry

router = APIRouter(prefix="/pool", tags=["pool"])


class DonorIn(BaseModel):
    token: str
    jobs: int = 20
    label: str | None = None


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
        "profile": row.profile,
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


@router.post("/machines/{name}/recycle", response_model=Ok)
async def recycle(name: str):
    if await registry.machine(name) is None:
        raise HTTPException(404, "no such machine")
    await leases.destroy(name, "recycled by the operator")
    return Ok(detail="destroyed")


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
