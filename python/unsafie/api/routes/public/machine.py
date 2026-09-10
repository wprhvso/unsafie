import contextlib
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from unsafie.pool import tunnels
from unsafie.settings import settings

logger = logging.getLogger(__name__)

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
