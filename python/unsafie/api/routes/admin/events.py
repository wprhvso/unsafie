import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from unsafie import events as bus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])

HEARTBEAT = 15.0


def _match(raw: str | None) -> dict:
    out: dict = {}
    for item in (raw or "").split(","):
        key, _, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if not key or not value:
            continue
        out[key] = int(value) if value.lstrip("-").isdigit() else value
    return out


def _frame(event: bus.Event) -> str:
    payload = json.dumps(
        {"id": event.id, "kind": event.kind, "at": event.at.isoformat(), "data": event.data},
        ensure_ascii=False,
        default=str,
    )
    return f"id: {event.id}\nevent: {event.kind}\ndata: {payload}\n\n"


@router.get("/recent")
async def recent(kinds: str | None = None, match: str | None = None, limit: int = 100):
    selected = [k.strip() for k in (kinds or "").split(",") if k.strip()] or None
    items = await bus.bus.recent(selected, _match(match) or None, min(limit, 500))
    oldest, latest = await bus.bus.bounds()
    return {
        "latest_id": latest,
        "oldest_id": oldest,
        "items": [
            {"id": e.id, "kind": e.kind, "at": e.at.isoformat(), "data": e.data} for e in items
        ],
    }


async def _stream(
    request: Request, kinds: list[str] | None, match: dict | None, after_id: str | None,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=512)

    async def pump() -> None:
        async for item in bus.subscribe(kinds, match, after_id):
            if item == bus.GAP:
                await queue.put("event: gap\ndata: {}\n\n")
            elif isinstance(item, bus.Event):
                await queue.put(_frame(item))

    task = asyncio.create_task(pump(), name="sse-pump")
    try:
        _, latest = await bus.bus.bounds()
        yield f": connected, latest={latest}\n\n"
        while True:
            if await request.is_disconnected():
                return
            try:
                yield await asyncio.wait_for(queue.get(), timeout=HEARTBEAT)
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        task.cancel()


@router.get("")
async def stream(
    request: Request,
    kinds: Annotated[str | None, Query()] = None,
    match: Annotated[str | None, Query()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after: Annotated[str | None, Query()] = None,
):
    selected = [k.strip() for k in (kinds or "").split(",") if k.strip()] or None
    after_id = after or last_event_id or None
    return StreamingResponse(
        _stream(request, selected, _match(match) or None, after_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
