import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from unsafie import tokens
from unsafie.database.models.api_token import TokenKind
from unsafie.pool import channel, donors, registry
from unsafie.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/machines", tags=["machines"])


class Registration(BaseModel):
    run_id: int | None = None
    profile: str = "fast"
    facts: dict = {}
    boot_seconds: float | None = None


class Output(BaseModel):
    frames: list[dict] = []


async def _machine(token: str | None, name: str) -> str:
    resolved = await tokens.resolve(token)
    if resolved is None or resolved.kind != TokenKind.MACHINE or resolved.machine != name:
        raise HTTPException(401, "this token does not drive that machine")
    return name


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return authorization


@router.post("/register")
async def register(
    body: Registration,
    x_unsafie_worker: Annotated[str | None, Header()] = None,
) -> dict:
    if not settings.pool_enabled:
        raise HTTPException(503, "the pool is switched off")
    if not x_unsafie_worker:
        raise HTTPException(401, "no worker token")
    donor = await donors.by_worker_token(x_unsafie_worker)
    if donor is None or not donor.enabled:
        raise HTTPException(401, "unknown or disabled donor")
    machine = await registry.register(
        donor.id, body.run_id, body.profile, body.facts, body.boot_seconds
    )
    _, raw = await tokens.issue(
        user_id=None,
        name=f"machine {machine.name}",
        kind=TokenKind.MACHINE,
        scopes=("pool",),
        machine=machine.name,
    )
    logger.info("machine %s registered by donor %s", machine.name, donor.login)
    return {
        "machine": machine.name,
        "token": raw,
        "poll": settings.pool_poll_timeout,
        "heartbeat": settings.pool_heartbeat,
    }


@router.post("/{name}/heartbeat")
async def beat(
    name: str,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    await _machine(_bearer(authorization), name)
    if not await registry.heartbeat(name):
        raise HTTPException(410, "this machine is no longer in the pool")
    return {"ok": True}


@router.get("/{name}/commands")
async def commands(
    name: str,
    wait: float | None = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    await _machine(_bearer(authorization), name)
    if not await registry.heartbeat(name):
        raise HTTPException(410, "this machine is no longer in the pool")
    patience = min(wait or settings.pool_poll_timeout, settings.pool_poll_timeout)
    return {"frames": await channel.pull(name, patience)}


@router.post("/{name}/output")
async def output(
    name: str,
    body: Output,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    await _machine(_bearer(authorization), name)
    await registry.heartbeat(name)
    grouped: dict[str, list[dict]] = {}
    for frame in body.frames:
        grouped.setdefault(str(frame.get("id") or ""), []).append(frame)
    for command_id, frames in grouped.items():
        if not command_id:
            continue
        if any(frame.get("kind") == "output" for frame in frames):
            await channel.started(command_id)
        await channel.push(command_id, frames)
    return {"accepted": len(body.frames)}


@router.post("/{name}/gone")
async def gone(
    name: str,
    reason: str = "exited",
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    await _machine(_bearer(authorization), name)
    await registry.forget(name, reason)
    await tokens.revoke_machine(name)
    return {"ok": True}
