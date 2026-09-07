import json
import logging
import os
import socket
import time
from datetime import UTC, datetime

from unsafie import cluster
from unsafie.agent import turns
from unsafie.loop import Loop
from unsafie.settings import settings
from unsafie.ssh.pool import pool
from unsafie.telegram.poller import supervisor

logger = logging.getLogger(__name__)

STARTED_AT = datetime.now(UTC)


def key(instance_id: str) -> str:
    return cluster.key("instance", instance_id)


def snapshot() -> dict:
    return {
        "instance": settings.instance_id,
        "role": settings.role,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": STARTED_AT.isoformat(),
        "uptime_sec": round(time.time() - STARTED_AT.timestamp()),
        "polling": supervisor.ids(),
        "turns": [str(t) for t in turns.busy()],
        "ssh_connections": len([s for s in pool.stats() if s["alive"]]),
    }


async def instances() -> list[dict]:
    client = cluster.client()
    found = [k async for k in client.scan_iter(match=key("*"), count=100)]
    if not found:
        return []
    out = []
    for raw in await client.mget(found):
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return sorted(out, key=lambda i: i.get("instance", ""))


class Presence(Loop):
    name = "presence"
    startup_delay = 1.0
    min_interval = 1.0

    @property
    def interval(self) -> float:
        return settings.presence_interval

    async def tick(self) -> None:
        await cluster.client().set(
            key(settings.instance_id),
            json.dumps(snapshot(), ensure_ascii=False, default=str),
            px=int(settings.presence_interval * 3 * 1000),
        )

    async def on_stop(self) -> None:
        try:
            await cluster.client().delete(key(settings.instance_id))
        except Exception:
            logger.warning("presence: could not withdraw %s", settings.instance_id, exc_info=True)


presence = Presence()
