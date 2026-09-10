import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from unsafie.agent import client, opal, request
from unsafie.api.routes.cli.deps import Who
from unsafie.database import SessionLocal
from unsafie.database.repositories.opal_session import OpalSessionRepository
from unsafie.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])

FIXED_MODEL = "gemini-flash-latest"
FIXED_EFFORT = "high"
MAX_EMPTY_RETRIES = 3


class LLMGenerateIn(BaseModel):
    system: str | None = None
    prompt: str | None = None
    parts: list[dict[str, Any]] | None = None
    messages: list[dict[str, Any]] | None = None


async def _get_access_token() -> str:
    tried = set()
    async with SessionLocal() as session:
        creds = OpalSessionRepository(session)
        session_row = await creds.pick(tried)
        if session_row is None:
            raise HTTPException(503, "no usable opal session available")
        try:
            return await opal.get_access_token(session_row.id, session_row.refresh_token)
        except Exception as e:
            logger.warning("opal session refresh failed: %s", e)
            raise HTTPException(503, f"failed to acquire opal access token: {e}") from e


def _format_parts(data: LLMGenerateIn) -> list[dict[str, Any]]:
    if data.messages:
        return data.messages

    parts: list[dict[str, Any]] = []
    if data.parts:
        for p in data.parts:
            p_type = p.get("type", "text")
            if p_type == "text" and p.get("text"):
                parts.append({"type": "text", "text": str(p["text"])})
            elif p_type == "image":
                source = p.get("source") or {}
                b64 = p.get("data") or source.get("data")
                mime = p.get("mime") or source.get("media_type") or "image/png"
                if b64:
                    parts.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
    elif data.prompt:
        parts.append({"type": "text", "text": data.prompt})

    return [{"role": "user", "content": parts}]


@router.post("/generate")
async def generate(data: LLMGenerateIn, who: Who) -> dict[str, Any]:
    access_token = await _get_access_token()
    system_prompt = data.system or ""
    history = _format_parts(data)

    last_reply = None
    for attempt in range(1, MAX_EMPTY_RETRIES + 1):
        body = request.build(
            model=FIXED_MODEL,
            prompt=system_prompt,
            messages=history,
            effort=FIXED_EFFORT,
            max_tokens=settings.gemini_max_output_tokens,
        )
        try:
            reply = await client.send(access_token, FIXED_MODEL, body)
            last_reply = reply
            if reply.text and reply.text.strip():
                return {
                    "ok": True,
                    "text": reply.text.strip(),
                    "thoughts": reply.thoughts.strip() if reply.thoughts else "",
                    "usage": reply.usage,
                    "attempts": attempt,
                }
            logger.warning("LLM attempt %s returned empty text (thoughts=%s chars), retrying...", attempt, len(reply.thoughts))
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("LLM generation error on attempt %s: %s", attempt, e)
            if attempt == MAX_EMPTY_RETRIES:
                raise HTTPException(502, f"LLM upstream error: {e}") from e
            await asyncio.sleep(1.0)

    return {
        "ok": True,
        "text": last_reply.text if last_reply else "",
        "thoughts": last_reply.thoughts if last_reply else "",
        "usage": last_reply.usage if last_reply else {},
        "attempts": MAX_EMPTY_RETRIES,
    }


@router.post("/stream")
async def stream(data: LLMGenerateIn, who: Who) -> StreamingResponse:
    access_token = await _get_access_token()
    system_prompt = data.system or ""
    history = _format_parts(data)

    async def event_generator() -> AsyncIterator[str]:
        yield f"event: start\ndata: {json.dumps({'model': FIXED_MODEL})}\n\n"

        body = request.build(
            model=FIXED_MODEL,
            prompt=system_prompt,
            messages=history,
            effort=FIXED_EFFORT,
            max_tokens=settings.gemini_max_output_tokens,
        )

        loop_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        def on_event(name: str, payload: dict[str, Any]) -> None:
            loop_queue.put_nowait((name, payload))

        send_task = asyncio.create_task(
            client.send(access_token, FIXED_MODEL, body, on_event=on_event)
        )

        done = False
        while not done:
            get_task = asyncio.create_task(loop_queue.get())
            finished, pending = await asyncio.wait([get_task, send_task], return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                if p is not send_task:
                    p.cancel()

            while not loop_queue.empty():
                evt_name, evt_data = loop_queue.get_nowait()
                if evt_name == "thought_delta":
                    yield f"event: thought\ndata: {json.dumps({'text': evt_data.get('thought', '')})}\n\n"
                elif evt_name == "text_delta":
                    yield f"event: delta\ndata: {json.dumps({'text': evt_data.get('text', '')})}\n\n"

            if send_task in finished:
                done = True
                try:
                    reply = await send_task
                    yield f"event: end\ndata: {json.dumps({'usage': reply.usage, 'text': reply.text, 'thoughts': reply.thoughts})}\n\n"
                except Exception as ex:
                    yield f"event: error\ndata: {json.dumps({'error': str(ex)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
