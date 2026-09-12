import asyncio
import contextlib

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from unsafie.log import get_logger
from unsafie.pool import tunnels
from unsafie.settings import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/api/m", tags=["desktop"])

GONE = 4404
SILENT = 4408
REFUSED = 4409
BROKEN = 1011
REASON_LIMIT = 100


@router.get("/{slug}")
async def describe(slug: str) -> dict:
    found = await tunnels.resolve(slug)
    if found is None:
        raise HTTPException(404, "this link has expired")
    return {"kind": found["kind"], "machine": found["machine"], "slug": slug}


def _subprotocol(websocket: WebSocket) -> str | None:
    offered = websocket.headers.get("sec-websocket-protocol", "")
    wanted = [item.strip() for item in offered.split(",") if item.strip()]
    return "binary" if "binary" in wanted else None


async def _refuse(websocket: WebSocket, code: int, reason: str) -> None:
    await websocket.close(code=code, reason=reason[:REASON_LIMIT])


@router.websocket("/{slug}/stream")
async def stream(websocket: WebSocket, slug: str) -> None:
    found = await tunnels.resolve(slug)
    await websocket.accept(subprotocol=_subprotocol(websocket))
    if found is None:
        logger.info("desktop %s: no such link", slug)
        await _refuse(websocket, GONE, "this link has expired")
        return

    if str(found.get("machine")) in ("local", "host") or found.get("local"):
        port = int(found["port"])
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError as broken:
            logger.warning("desktop %s: local connect failed: %s", slug, broken)
            await _refuse(websocket, REFUSED, f"local connect failed: {broken}")
            return

        done = asyncio.Event()

        async def ws_to_tcp():
            try:
                while not done.is_set():
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    data = msg.get("bytes")
                    if data is None and msg.get("text") is not None:
                        data = msg["text"].encode()
                    if data:
                        writer.write(data)
                        await writer.drain()
            except Exception:
                pass
            finally:
                done.set()

        async def tcp_to_ws():
            try:
                while not done.is_set():
                    data = await reader.read(65536)
                    if not data:
                        break
                    await websocket.send_bytes(data)
            except Exception:
                pass
            finally:
                done.set()

        tasks = [asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        return

    machine = str(found["machine"])
    channel_id = ""
    opened = None
    try:
        channel_id = await tunnels.open_channel(machine, str(found["kind"]), int(found["port"]))
        opened = await tunnels.bridge(channel_id, tunnels.BROWSER)
        ready = await tunnels.wait_for_machine(channel_id, settings.pool_tunnel_wait)
        if ready is None:
            logger.warning(
                "desktop %s: %s never dialled back in %ss",
                slug,
                machine,
                settings.pool_tunnel_wait,
            )
            await _refuse(websocket, SILENT, "the machine never dialled back")
            return
        if not ready.ok:
            await _refuse(websocket, REFUSED, ready.reason or "the machine refused the tunnel")
            return
        await opened.pump(websocket)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("desktop %s: the tunnel broke", slug)
        with contextlib.suppress(RuntimeError):
            await _refuse(websocket, BROKEN, "the tunnel broke on the server")
    finally:
        if opened is not None:
            await opened.close()
        if channel_id:
            await tunnels.forget(channel_id)
