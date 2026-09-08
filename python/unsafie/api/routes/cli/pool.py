import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from unsafie.api.routes.cli.deps import Pool
from unsafie.database import SessionLocal
from unsafie.database.models.pool import CommandStatus, PoolCommand, PoolMachine, PoolUsage
from unsafie.database.models.user import User
from unsafie.errors import OpsError
from unsafie.pool import channel, leases, registry, tunnels
from unsafie.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pool", tags=["cli"])


class Take(BaseModel):
    count: int = 1
    wait: float | None = None
    turn: str | None = None


class Release(BaseModel):
    machine: str | None = None


class Run(BaseModel):
    command: str
    machine: str | None = None
    timeout: float | None = None
    cwd: str | None = None
    stdin: str | None = None
    turn: str | None = None
    background: bool = False


class Rename(BaseModel):
    machine: str
    alias: str


def _view(machine: PoolMachine) -> dict:
    return {
        "name": machine.name,
        "alias": machine.alias,
        "state": machine.state,
        "profile": machine.profile,
        "started_at": machine.started_at,
        "leased_at": machine.leased_at,
        "facts": machine.facts,
    }


def _turn(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


@router.get("/machines")
async def machines(who: Pool) -> dict:
    mine = await registry.of_user(who.user_id)
    return {
        "machines": [_view(machine) for machine in mine],
        "capacity": await registry.counted(),
        "idle_after": settings.pool_lease_idle,
    }


@router.post("/take")
async def take(body: Take, who: Pool) -> dict:
    try:
        taken = await leases.take(
            who.user_id,
            who.chat_id,
            max(1, min(body.count, 20)),
            body.wait,
            _turn(body.turn),
            who.bot_id,
        )
    except OpsError as refused:
        raise HTTPException(409, str(refused)) from None
    return {"machines": [_view(machine) for machine in taken]}


@router.post("/release")
async def release(body: Release, who: Pool) -> dict:
    try:
        gone = await leases.release(who.user_id, body.machine)
    except OpsError as refused:
        raise HTTPException(404, str(refused)) from None
    return {"released": gone}


@router.post("/run")
async def run(body: Run, who: Pool) -> dict:
    try:
        machine = await leases.resolve(who.user_id, body.machine)
    except OpsError as refused:
        raise HTTPException(404, str(refused)) from None
    if body.background:
        command_id = await channel.send(
            machine.name,
            body.command,
            user_id=who.user_id,
            turn_id=_turn(body.turn),
            cwd=body.cwd,
            timeout=body.timeout,
            background=True,
        )
        channel.drain(command_id, machine.name, body.timeout)
        return {"job": command_id, "machine": machine.alias or machine.name}
    result = await channel.run(
        machine.name,
        body.command,
        user_id=who.user_id,
        turn_id=_turn(body.turn),
        cwd=body.cwd,
        timeout=body.timeout,
        stdin=body.stdin,
    )
    return {
        "machine": machine.alias or machine.name,
        "exit_code": result.exit_code,
        "output": result.output,
        "seconds": round(result.seconds, 2),
        "truncated": result.truncated,
        "timed_out": result.timed_out,
    }


class Desktop(BaseModel):
    kind: str = "vnc"
    display: str | None = None
    port: int | None = None
    machine: str | None = None


@router.post("/desktop")
async def desktop(body: Desktop, who: Pool) -> dict:
    if body.kind not in ("vnc", "term"):
        raise HTTPException(400, "kind must be vnc or term")
    try:
        machine = await leases.resolve(who.user_id, body.machine or who.machine)
    except OpsError as refused:
        raise HTTPException(404, str(refused)) from None
    port = body.port or (settings.pool_vnc_port if body.kind == "vnc" else 0)
    slug = await tunnels.publish(who.user_id, machine.name, body.kind, port)
    return {
        "url": f"{settings.public_origin}/m/{slug}",
        "slug": slug,
        "kind": body.kind,
        "machine": machine.alias or machine.name,
        "expires_in": settings.pool_desktop_ttl,
    }


@router.get("/quota")
async def quota(who: Pool) -> dict:
    async with SessionLocal() as session:
        user = await session.get(User, who.user_id)
    mine = await registry.of_user(who.user_id)
    limits = {
        "machines": user.pool_max_machines if user else 3,
        "background": user.pool_max_background if user else 10,
        "minutes_day": user.pool_max_minutes_day if user else 600,
        "priority": user.pool_priority if user else 0,
        "blocked": bool(user.pool_blocked) if user else False,
    }
    today = date.today()
    async with SessionLocal() as session:
        usage = await session.scalar(
            select(PoolUsage).where(PoolUsage.user_id == who.user_id, PoolUsage.day == today)
        )
    return {
        "limits": limits,
        "held": len(mine),
        "used_today": {
            "machine_minutes": round((usage.machine_seconds if usage else 0) / 60, 1),
            "commands": usage.commands if usage else 0,
        },
        "capacity": await registry.counted(),
    }


@router.post("/rename")
async def rename(body: Rename, who: Pool) -> dict:
    try:
        machine = await leases.resolve(who.user_id, body.machine)
    except OpsError as refused:
        raise HTTPException(404, str(refused)) from None
    alias = body.alias.strip()[:32]
    if not alias:
        raise HTTPException(400, "an empty name says nothing")
    await leases.rename(machine.name, alias)
    return {"machine": machine.name, "alias": alias}


def _job_view(row: PoolCommand) -> dict:
    return {
        "job": str(row.id),
        "machine": row.machine,
        "status": row.status,
        "exit_code": row.exit_code,
        "command": row.command,
        "background": row.background,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


@router.get("/jobs")
async def jobs(who: Pool, limit: int = 20, background: bool = True) -> dict:
    async with SessionLocal() as session:
        query = (
            select(PoolCommand)
            .where(PoolCommand.user_id == who.user_id)
            .order_by(PoolCommand.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        if background:
            query = query.where(PoolCommand.background.is_(True))
        rows = await session.scalars(query)
        return {"jobs": [_job_view(row) for row in rows]}


@router.get("/jobs/{job_id}")
async def job(job_id: str, who: Pool, wait: float = 0.0, since: int = 0) -> dict:
    row = await _own_job(job_id, who.user_id)
    if wait > 0 and row.status not in (CommandStatus.DONE, CommandStatus.FAILED, CommandStatus.LOST):
        await channel.collect(job_id, row.machine, wait)
        row = await _own_job(job_id, who.user_id)
    whole = await channel.tail(job_id)
    return {**_job_view(row), "output": whole[max(0, since) :], "read": len(whole)}


@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str, who: Pool) -> dict:
    row = await _own_job(job_id, who.user_id)
    if row.status in (CommandStatus.DONE, CommandStatus.FAILED, CommandStatus.LOST):
        return {"job": job_id, "status": row.status, "note": "already finished"}
    await channel.cancel(job_id, row.machine)
    return {"job": job_id, "status": CommandStatus.CANCELLED}


async def _own_job(job_id: str, user_id: int) -> PoolCommand:
    try:
        wanted = UUID(job_id)
    except ValueError:
        raise HTTPException(404, "no such job") from None
    async with SessionLocal() as session:
        row = await session.scalar(select(PoolCommand).where(PoolCommand.id == wanted))
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "no such job")
    return row
