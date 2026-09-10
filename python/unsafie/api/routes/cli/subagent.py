import contextlib
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from unsafie import artifacts, cluster
from unsafie.agent import live
from unsafie.agent.runtime import spawn_subagent_task
from unsafie.agent.subagents import wait_subagents
from unsafie.agent.turns import stop
from unsafie.api.routes.cli.deps import Who
from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository
from unsafie.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subagents", tags=["subagents"])


class SpawnIn(BaseModel):
    prompt: str
    title: str | None = None
    timeout: float = 600.0
    parent_turn_id: str | None = None


class WaitIn(BaseModel):
    ids: list[str]
    timeout: float = 600.0


class CancelIn(BaseModel):
    ids: list[str]


class ResultIn(BaseModel):
    result: str


def _format_turn(t: Turn, token: str | None = None) -> dict:
    url = (
        f"{settings.artifact_origin}/{token}"
        if token
        else f"{settings.artifact_origin}/turn/{t.id}"
    )
    return {
        "id": str(t.id),
        "title": t.title,
        "status": t.status,
        "result": t.result,
        "steps": t.num_turns,
        "live_url": url,
        "created_at": t.created_at,
        "finished_at": t.finished_at,
    }


@router.post("")
async def spawn_subagent(body: SpawnIn, who: Who) -> dict:
    parent = await who.turn(body.parent_turn_id)
    if parent is None and who.chat_id and who.bot_id:
        async with SessionLocal() as session:
            running = await TurnRepository(session).running(who.bot_id, who.chat_id)
            if running:
                parent = running[-1]
    if parent is None:
        raise HTTPException(
            400, "active parent turn required: pass parent_turn_id or set UNSAFIE_TURN",
        )

    title = body.title or (body.prompt[:40] + "…" if len(body.prompt) > 40 else body.prompt)
    async with SessionLocal() as session:
        child = await TurnRepository(session).create_subagent(
            parent=parent,
            title=title,
        )

    slug = await artifacts.for_turn(child)
    if slug:
        with contextlib.suppress(Exception):
            client = cluster.client()
            ttl = int(settings.live_ttl * 1000)
            await client.set(live.token_key(slug), str(child.id), px=ttl)
            await client.set(live.link_key(child.id), slug, px=ttl)
    live_url = artifacts.url(slug) if slug else f"{settings.artifact_origin}/turn/{child.id}"

    live.emit(
        parent.id,
        "note",
        name="subagent.spawned",
        attributes={"subagent_id": str(child.id), "title": child.title, "live_url": live_url},
    )

    spawn_subagent_task(child.id, body.prompt, timeout=body.timeout)
    logger.info("subagent %s spawned by turn=%s title=%s", child.id, parent.id, child.title)
    return {
        "id": str(child.id),
        "title": child.title,
        "status": child.status,
        "live_url": live_url,
    }


@router.post("/wait")
async def wait_for_subagents(body: WaitIn, who: Who) -> list[dict]:
    uuids: list[UUID] = []
    for raw_id in body.ids:
        try:
            uuids.append(UUID(raw_id))
        except ValueError:
            raise HTTPException(400, f"invalid uuid: {raw_id}") from None

    await wait_subagents(uuids, timeout=body.timeout)

    results: list[dict] = []
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        for uid in uuids:
            t = await repo.get(uid)
            if t is not None and t.user_id == who.user_id:
                slug = await artifacts.of_turn(t.id)
                results.append(_format_turn(t, slug))
            else:
                results.append({"id": str(uid), "status": "unknown", "result": None})
    return results


@router.get("")
async def list_subagents(
    who: Who, parent_turn_id: str | None = None, limit: int = 50,
) -> list[dict]:
    parent = await who.turn(parent_turn_id)
    if parent is None and who.chat_id and who.bot_id:
        async with SessionLocal() as session:
            running = await TurnRepository(session).running(who.bot_id, who.chat_id)
            if running:
                parent = running[-1]
    if parent is None:
        return []
    async with SessionLocal() as session:
        children = await TurnRepository(session).subagents(parent.id)
    out: list[dict] = []
    for c in children[:limit]:
        slug = await artifacts.of_turn(c.id)
        out.append(_format_turn(c, slug))
    return out


@router.get("/{turn_id}")
async def get_subagent(turn_id: str, who: Who) -> dict:
    try:
        uid = UUID(turn_id)
    except ValueError:
        raise HTTPException(400, "invalid uuid") from None
    async with SessionLocal() as session:
        t = await TurnRepository(session).get(uid)
    if t is None or not t.is_subagent:
        raise HTTPException(404, "no such subagent")
    if t.user_id != who.user_id:
        raise HTTPException(403, "access denied")
    slug = await artifacts.of_turn(t.id)
    return _format_turn(t, slug)


@router.post("/cancel")
async def cancel_subagents(body: CancelIn, who: Who) -> dict:
    cancelled = []
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        for raw_id in body.ids:
            try:
                uid = UUID(raw_id)
                t = await repo.get(uid)
                if t is not None and t.user_id == who.user_id:
                    await stop(uid)
                    cancelled.append(str(uid))
            except ValueError:
                pass
    return {"cancelled": cancelled}


@router.post("/{turn_id}/result")
async def set_subagent_result(turn_id: str, body: ResultIn, who: Who) -> dict:
    try:
        uid = UUID(turn_id)
    except ValueError:
        raise HTTPException(400, "invalid uuid") from None
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        t = await repo.get(uid)
        if t is None or not t.is_subagent:
            raise HTTPException(404, "no such subagent")
        if t.user_id != who.user_id:
            raise HTTPException(403, "access denied")
        await repo.set_result(uid, body.result)
    return {"id": turn_id, "recorded": True}
