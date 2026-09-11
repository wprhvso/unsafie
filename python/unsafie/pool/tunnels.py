import asyncio
import contextlib
import json
import logging
import secrets
import time
from dataclasses import dataclass

from unsafie import cluster
from unsafie.pool import channel, keys
from unsafie.settings import settings
from unsafie_wire import channel as wire

logger = logging.getLogger(__name__)

KINDS = ("vnc", "term")
BROWSER = "browser"
MACHINE = "machine"
EOF = b""
IDLE = 0.5
BLOCK = max(1, int(min(5.0, settings.redis_timeout - 1)))


def slug_key(slug: str) -> str:
    return keys.desktop(slug)


def _ttl() -> int:
    return int(settings.pool_tunnel_wait) + 60


async def _load(name: str) -> dict | None:
    stored = await cluster.client().get(name)
    if stored is None:
        return None
    try:
        found = json.loads(stored)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


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
    return await _load(slug_key(slug))


async def open_channel(machine: str, kind: str, port: int) -> str:
    channel_id = secrets.token_urlsafe(12)
    await cluster.client().set(
        keys.tunnel(channel_id),
        json.dumps({"machine": machine, "kind": kind, "port": port}),
        ex=_ttl(),
    )
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
    logger.info("pool tunnel %s asked of %s (%s on %s)", channel_id, machine, kind, port)
    return channel_id


async def pending(channel_id: str) -> dict | None:
    return await _load(keys.tunnel(channel_id))


async def forget(channel_id: str) -> None:
    await cluster.client().delete(keys.tunnel(channel_id), keys.tunnel_ready(channel_id))


@dataclass(frozen=True)
class Ready:
    ok: bool
    reason: str = ""


async def _signal(channel_id: str, value: str) -> None:
    redis = cluster.client()
    name = keys.tunnel_ready(channel_id)
    await redis.rpush(name, value)
    await redis.expire(name, _ttl())


async def announce(channel_id: str) -> None:
    await _signal(channel_id, "yes")


async def refuse(channel_id: str, reason: str) -> None:
    await _signal(channel_id, f"no:{reason}")
    logger.info("pool tunnel %s refused by the machine: %s", channel_id, reason)


async def wait_for_machine(channel_id: str, timeout: float) -> Ready | None:
    redis = cluster.client()
    name = keys.tunnel_ready(channel_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        popped = await redis.blpop([name], timeout=BLOCK)
        if popped is None:
            continue
        value = str(popped[1])
        return Ready(False, value[3:]) if value.startswith("no:") else Ready(True)
    return None


class Bridge:
    def __init__(self, channel_id: str, side: str) -> None:
        self.channel_id = channel_id
        self.side = side
        mine, theirs = (keys.tunnel_down, keys.tunnel_up)
        if side == BROWSER:
            mine, theirs = theirs, mine
        self.mine = mine(channel_id)
        self.theirs = theirs(channel_id)
        self._subscriber = None

    async def open(self) -> "Bridge":
        self._subscriber = cluster.binary().pubsub(ignore_subscribe_messages=True)
        await self._subscriber.subscribe(self.theirs)
        return self

    async def close(self) -> None:
        subscriber, self._subscriber = self._subscriber, None
        if subscriber is None:
            return
        with contextlib.suppress(Exception):
            await subscriber.unsubscribe(self.theirs)
        closer = getattr(subscriber, "aclose", None) or subscriber.close
        with contextlib.suppress(Exception):
            await closer()

    async def pump(self, socket) -> None:
        subscriber = self._subscriber
        if subscriber is None:
            msg = "the bridge was never opened"
            raise RuntimeError(msg)
        raw = cluster.binary()
        done = asyncio.Event()

        async def outward() -> None:
            try:
                while True:
                    message = await socket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    data = message.get("bytes")
                    if data is None and message.get("text") is not None:
                        data = message["text"].encode()
                    if data:
                        await raw.publish(self.mine, data)
            finally:
                done.set()
                with contextlib.suppress(Exception):
                    await raw.publish(self.mine, EOF)

        async def inward() -> None:
            try:
                while not done.is_set():
                    message = await subscriber.get_message(timeout=IDLE)
                    if message is None:
                        continue
                    data = message.get("data") or EOF
                    if data == EOF:
                        return
                    await socket.send_bytes(data)
            finally:
                done.set()

        crew = [
            asyncio.create_task(outward(), name=f"tunnel-out:{self.channel_id}"),
            asyncio.create_task(inward(), name=f"tunnel-in:{self.channel_id}"),
        ]
        try:
            await asyncio.wait(crew, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in crew:
                task.cancel()
            await asyncio.gather(*crew, return_exceptions=True)
            await self.close()


async def bridge(channel_id: str, side: str) -> Bridge:
    return await Bridge(channel_id, side).open()
