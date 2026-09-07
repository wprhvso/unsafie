import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field

from unsafie import cluster
from unsafie.pool import channel, keys
from unsafie.settings import settings
from unsafie_wire import channel as wire

logger = logging.getLogger(__name__)

KINDS = ("vnc", "term")


@dataclass
class Pending:
    machine: str
    kind: str
    port: int
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    machine_side: object | None = None


_WAITING: dict[str, Pending] = {}


def slug_key(slug: str) -> str:
    return cluster.key(keys.NAMESPACE, "desktop", slug)


async def publish(user_id: int, machine: str, kind: str, port: int) -> str:
    slug = secrets.token_urlsafe(9)
    await cluster.client().set(
        slug_key(slug),
        json.dumps({"user": user_id, "machine": machine, "kind": kind, "port": port}),
        ex=int(settings.pool_desktop_ttl),
    )
    logger.info("pool desktop %s -> %s:%s (%s)", slug, machine, port, kind)
    return slug


async def resolve(slug: str) -> dict | None:
    stored = await cluster.client().get(slug_key(slug))
    if stored is None:
        return None
    try:
        return json.loads(stored)
    except ValueError:
        return None


async def open_channel(machine: str, kind: str, port: int) -> str:
    channel_id = secrets.token_urlsafe(12)
    _WAITING[channel_id] = Pending(machine, kind, port)
    await channel.tell(
        machine,
        wire.Frame(
            wire.FrameKind.COMMAND,
            f"tunnel-{channel_id}",
            {
                "command": "",
                "tunnel": {"channel": channel_id, "kind": kind, "port": port},
                "background": True,
            },
        ),
    )
    return channel_id


def pending(channel_id: str) -> Pending | None:
    return _WAITING.get(channel_id)


def attach(channel_id: str, socket: object) -> Pending | None:
    waiting = _WAITING.get(channel_id)
    if waiting is None:
        return None
    waiting.machine_side = socket
    waiting.ready.set()
    return waiting


def forget(channel_id: str) -> None:
    waiting = _WAITING.pop(channel_id, None)
    if waiting is not None:
        waiting.closed.set()


async def wait_for_machine(channel_id: str, timeout: float) -> Pending | None:
    waiting = _WAITING.get(channel_id)
    if waiting is None:
        return None
    try:
        await asyncio.wait_for(waiting.ready.wait(), timeout=timeout)
    except TimeoutError:
        forget(channel_id)
        return None
    return waiting
