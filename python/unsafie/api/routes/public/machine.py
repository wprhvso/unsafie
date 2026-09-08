import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from unsafie.pool import tunnels
from unsafie.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/m", tags=["desktop"])


@router.get("/{slug}")
async def describe(slug: str) -> dict:
    found = await tunnels.resolve(slug)
    if found is None:
        raise HTTPException(404, "this link has expired")
    return {"kind": found["kind"], "machine": found["machine"], "slug": slug}


@router.websocket("/{slug}/stream")
async def stream(websocket: WebSocket, slug: str) -> None:
    found = await tunnels.resolve(slug)
    if found is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    channel_id = await tunnels.open_channel(found["machine"], found["kind"], int(found["port"]))
    waiting = await tunnels.wait_for_machine(channel_id, settings.pool_tunnel_wait)
    if waiting is None or waiting.machine_side is None:
        await websocket.close(code=4408)
        return
    machine_socket = waiting.machine_side
    try:
        await _pipe(websocket, machine_socket)
    finally:
        tunnels.forget(channel_id)


async def _pipe(browser: WebSocket, machine) -> None:
    async def upstream() -> None:
        while True:
            message = await browser.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes")
            if data is None and message.get("text") is not None:
                data = message["text"].encode()
            if data:
                await machine.send_bytes(data)

    async def downstream() -> None:
        while True:
            data = await machine.receive_bytes()
            await browser.send_bytes(data)

    crew = [asyncio.create_task(upstream()), asyncio.create_task(downstream())]
    try:
        done, pending = await asyncio.wait(crew, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        for task in crew:
            task.cancel()
        await asyncio.gather(*crew, return_exceptions=True)
