import asyncio
import json
from unsafie.log import get_logger
import time
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError

from unsafie import cluster
from unsafie.agent import live
from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository
from unsafie.settings import settings
from unsafie.slugs import is_slug

logger = get_logger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

HEARTBEAT = 15.0
DOWN = (cluster.Unavailable, RedisError, OSError)
GONE = "this link has expired"


async def _resolve(token: str) -> UUID:
    if not is_slug(token):
        raise HTTPException(404, GONE)
    try:
        turn_id = await live.turn_of(token)
    except DOWN as e:
        logger.warning("live: token %s could not be resolved: %s", token, e)
        raise HTTPException(503, "the event store is unavailable") from e
    if turn_id is None:
        raise HTTPException(404, GONE)
    return turn_id


def _meta(turn: Turn | None) -> dict:
    if turn is None:
        return {"status": "unknown"}
    return {
        "id": str(turn.id)[:8],
        "status": turn.status,
        "steps": turn.num_turns,
        "created_at": turn.created_at,
        "finished_at": turn.finished_at,
    }


@router.get("/{token}")
async def snapshot(
    token: str,
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100_000)] = 20_000,
):
    turn_id = await _resolve(token)
    async with SessionLocal() as session:
        turn = await TurnRepository(session).get(turn_id)
    try:
        events = await live.history(turn_id, after, limit)
        oldest, latest = await live.bounds(turn_id)
    except DOWN as e:
        raise HTTPException(503, "the event store is unavailable") from e
    return {
        "token": token,
        "turn": _meta(turn),
        "oldest_id": oldest,
        "latest_id": latest,
        "events": events,
    }


def _sse(item: dict) -> str:
    payload = json.dumps(item, ensure_ascii=False, default=str)
    return f"id: {item.get('id', '')}\ndata: {payload}\n\n"


async def _pump(queue: asyncio.Queue, turn_id: UUID, after: str | None) -> None:
    try:
        async for item in live.follow(turn_id, after):
            if item == live.GAP:
                await queue.put("event: gap\ndata: {}\n\n")
                continue
            if isinstance(item, dict):
                await queue.put(_sse(item))
                if item.get("kind") == "turn.end":
                    break
    except asyncio.CancelledError:
        raise
    except DOWN:
        logger.warning("live: turn=%s stream broke", turn_id, exc_info=True)
    await queue.put(None)


async def _body(request: Request, turn_id: UUID, after: str | None) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
    task = asyncio.create_task(_pump(queue, turn_id, after), name=f"live-sse:{turn_id}")
    deadline = time.monotonic() + settings.live_stream_seconds
    try:
        yield ": open\n\n"
        while True:
            if await request.is_disconnected() or time.monotonic() > deadline:
                return
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is None:
                yield "event: done\ndata: {}\n\n"
                return
            yield item
    finally:
        task.cancel()


@router.get("/{token}/stream")
async def stream(
    request: Request,
    token: str,
    after: Annotated[str | None, Query()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    turn_id = await _resolve(token)
    return StreamingResponse(
        _body(request, turn_id, after or last_event_id or None),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
