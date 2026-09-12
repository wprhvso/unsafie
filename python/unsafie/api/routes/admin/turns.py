import json
from typing import Annotated
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException

from unsafie import artifacts
from unsafie.agent import live
from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import ResponseRead, TurnDetail, TurnRead
from unsafie.database import SessionLocal
from unsafie.database.models.turn_message import TurnMessages
from unsafie.database.repositories.turn import TurnRepository
from unsafie.log import get_logger
from unsafie.settings import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/turns", tags=["turns"])


@router.get("", response_model=Page[TurnRead])
async def list_turns(
    params: Annotated[PageParams, Depends(paging)],
    bot_id: int | None = None,
    chat_id: int | None = None,
    user_id: int | None = None,
    status: str | None = None,
):
    async with SessionLocal() as session:
        rows, total = await TurnRepository(session).page(
            params.offset, params.limit, bot_id, chat_id, user_id, status,
        )
    return Page.of([TurnRead.model_validate(r) for r in rows], total, params)


@router.get("/{turn_id}/live")
async def live_link(turn_id: UUID):
    try:
        token = await live.token_of(turn_id)
    except Exception as e:
        logger.warning("turn=%s live token unreadable: %s", turn_id, e)
        token = None
    return {"token": token, "url": artifacts.url(token) if token else None}


@router.get("/{turn_id}/trace")
async def get_turn_trace(turn_id: UUID):
    trace_data = None
    spans = []
    logs_data = []

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5.0)) as client:
        try:
            params = {
                "service": settings.service_name,
                "tags": json.dumps({"unsafie.turn_id": str(turn_id)}),
                "limit": "1",
            }
            async with client.get(f"{settings.victoriatraces_url}/select/jaeger/api/traces", params=params) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    items = payload.get("data", [])
                    if items:
                        trace_data = items[0]
        except Exception as e:
            logger.warning("trace.fetch_failed", turn_id=str(turn_id), error=str(e))

        try:
            logsql = f'turn_id:"{turn_id}"'
            async with client.get(f"{settings.victorialogs_url}/select/logsql/query", params={"query": logsql}) as resp:
                if resp.status == 200:
                    raw = await resp.text()
                    for line in raw.splitlines():
                        line = line.strip()
                        if line:
                            try:
                                logs_data.append(json.loads(line))
                            except Exception:
                                pass
        except Exception as e:
            logger.warning("logs.fetch_failed", turn_id=str(turn_id), error=str(e))

    total_duration_ms = 0.0
    trace_id = None
    if trace_data and trace_data.get("spans"):
        raw_spans = trace_data["spans"]
        trace_id = trace_data.get("traceID")
        min_start = min(s.get("startTime", 0) for s in raw_spans)
        max_end = max(s.get("startTime", 0) + s.get("duration", 0) for s in raw_spans)
        total_duration_ms = max(0.1, (max_end - min_start) / 1000.0)

        for s in raw_spans:
            s_start = s.get("startTime", 0)
            s_dur = s.get("duration", 0)
            parent_id = None
            for ref in s.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    parent_id = ref.get("spanID")
                    break

            tags = {t.get("key"): t.get("value") for t in s.get("tags", [])}
            is_error = tags.get("error") is True or tags.get("otel.status_code") == "ERROR"

            spans.append({
                "id": s.get("spanID"),
                "parent_id": parent_id,
                "name": s.get("operationName", "span"),
                "start_ms": round(max(0.0, (s_start - min_start) / 1000.0), 2),
                "duration_ms": round(s_dur / 1000.0, 2),
                "status": "error" if is_error else "ok",
                "tags": tags,
            })

        spans.sort(key=lambda x: (x["start_ms"], -x["duration_ms"]))

    logs_data.sort(key=lambda x: x.get("timestamp") or x.get("_time") or "")

    return {
        "trace_id": trace_id,
        "total_duration_ms": round(total_duration_ms, 2),
        "spans": spans,
        "logs": logs_data,
    }


@router.get("/{turn_id}", response_model=TurnDetail)
async def get_turn(turn_id: UUID):
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        turn = await repo.get(turn_id)
        if turn is None:
            raise HTTPException(404, "no such turn")
        parent = await repo.get(turn.parent_id) if turn.parent_id else None
        children = await repo.children(turn_id)
        conversation = await repo.conversation(turn.root_id)
        responses = await repo.responses(turn_id)
        segment = await session.get(TurnMessages, turn_id)
    return TurnDetail(
        turn=TurnRead.model_validate(turn),
        parent=TurnRead.model_validate(parent) if parent else None,
        children=[TurnRead.model_validate(c) for c in children],
        conversation=[TurnRead.model_validate(c) for c in conversation],
        responses=[ResponseRead.model_validate(r) for r in responses],
        messages=segment.count if segment else 0,
    )
