"""Redis: what several unsafie processes have to agree on right now.

Postgres stays the source of truth — turns, updates, credentials, worktrees, tasks live there
and outlive everything. This is the other half of a stateless deployment: the state that only
exists while it is happening and that a second instance must see immediately. Who is routing a
message in this chat, which turn is running and where, an installation token with a ttl, a
snapshot somebody is already downloading.

Nothing here degrades quietly. A lock that turns into a no-op when redis is unreachable is worse
than no lock at all, so the pool is opened in the lifespan and a failure there stops the process.

    from unsafie import cluster

    async with cluster.lock(f"chat:{bot_id}:{chat_id}"):
        ...

    async with cluster.try_lock(f"snapshot:{repo}:{sha}", renew=True) as held:
        if held is None:
            return  # somebody else is already downloading it
"""

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from redis.asyncio import Redis
from redis.exceptions import RedisError

from unsafie import telemetry
from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

EXTEND = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""

HEALTH_CHECK = 30.0

_client: Redis | None = None
_release = None
_extend = None


class Unavailable(RuntimeError):
    """Redis was never connected — connect() runs in the lifespan, before anything needs it."""


class Busy(RuntimeError):
    """Somebody else holds the lock and waiting did not help."""


def key(*parts: str | int) -> str:
    """Every key of this deployment lives under one prefix, so one redis can serve several."""
    return ":".join([settings.redis_prefix, *(str(p) for p in parts)])


def safe_url(url: str) -> str:
    """The url without the password: it ends up in logs and in /health."""
    parsed = urlsplit(url)
    if not parsed.password:
        return url
    user = parsed.username or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{user}:«redacted»@{parsed.hostname or ''}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


async def connect() -> Redis:
    """Open the pool. Idempotent, and fatal on failure — see the module docstring."""
    global _client, _release, _extend
    if _client is not None:
        return _client
    opened = Redis.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        socket_timeout=settings.redis_timeout,
        socket_connect_timeout=settings.redis_timeout,
        socket_keepalive=True,
        health_check_interval=HEALTH_CHECK,
        decode_responses=True,
    )
    try:
        await opened.ping()
    except (RedisError, OSError) as e:
        await opened.aclose()
        raise Unavailable(f"redis at {safe_url(settings.redis_url)} is not reachable: {e}") from e
    _client = opened
    _release = opened.register_script(RELEASE)
    _extend = opened.register_script(EXTEND)
    logger.info(
        "redis connected: %s prefix=%s instance=%s role=%s",
        safe_url(settings.redis_url),
        settings.redis_prefix,
        settings.instance_id,
        settings.role,
    )
    return opened


def client() -> Redis:
    if _client is None:
        raise Unavailable("redis is not connected")
    return _client


async def close() -> None:
    global _client, _release, _extend
    if _client is not None:
        await _client.aclose()
        logger.info("redis pool closed")
    _client = _release = _extend = None


async def health() -> dict:
    """One PING. Cheap enough to sit on the /health probe, honest enough to fail it."""
    started = time.perf_counter()
    try:
        await client().ping()
    except (Unavailable, RedisError, OSError) as e:
        return {"status": "down", "error": str(e)[:200]}
    return {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}


@dataclass
class Held:
    """A lock in hand. `token` is what makes releasing it safe: only the owner may unlock."""

    name: str
    key: str
    token: str
    ttl: float
    taken_at: float

    @property
    def age(self) -> float:
        return time.monotonic() - self.taken_at

    async def extend(self, ttl: float | None = None) -> bool:
        """Push the expiry away. False means it is gone and somebody else may hold it now."""
        ms = int((ttl or self.ttl) * 1000)
        return bool(await _extend(keys=[self.key], args=[self.token, ms]))

    async def release(self) -> bool:
        return bool(await _release(keys=[self.key], args=[self.token]))


async def acquire(name: str, *, ttl: float | None = None, wait: float = 0.0) -> Held | None:
    """Take the lock, retrying for up to `wait` seconds. None means somebody else has it.

    Polling rather than a notification on purpose: the critical sections here are short (routing
    a message, claiming a task) and a `SET NX PX` every 50 ms is cheaper than the plumbing a
    pub/sub wakeup would need.
    """
    ttl = ttl or settings.lock_ttl
    full = key("lock", name)
    token = f"{settings.instance_id}:{secrets.token_hex(4)}"
    deadline = time.monotonic() + wait
    while True:
        if await client().set(full, token, nx=True, px=int(ttl * 1000)):
            return Held(name, full, token, ttl, time.monotonic())
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(settings.lock_retry)


async def lease(name: str, ttl: float) -> bool:
    """Claim something once: True for the first caller, False for the rest until the ttl runs out.

    Unlike a lock this is never released. It is a marker — "this task has already fired", "this
    snapshot was refused" — not a critical section.
    """
    return bool(
        await client().set(key("lease", name), settings.instance_id, nx=True, px=int(ttl * 1000))
    )


async def _keep(held: Held) -> None:
    """Hold the lock for as long as the block runs: a slow rebase must not lose it mid-flight."""
    while True:
        await asyncio.sleep(held.ttl / 3)
        try:
            alive = await held.extend()
        except RedisError:
            logger.warning("lock %s could not be extended", held.name, exc_info=True)
            return
        if not alive:
            logger.warning("lock %s expired under us after %.1fs", held.name, held.age)
            return


@contextlib.asynccontextmanager
async def _holding(held: Held, renew: bool) -> AsyncIterator[None]:
    keeper = asyncio.create_task(_keep(held), name=f"lock:{held.name}") if renew else None
    try:
        yield
    finally:
        if keeper is not None:
            keeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keeper
        with contextlib.suppress(RedisError):
            await held.release()


def _note(name: str, waited: float, taken: bool) -> None:
    """Contention is the interesting part of a lock: it is the only thing worth a log line."""
    if waited < settings.lock_retry:
        return
    logger.info("lock %s %s after %.0fms", name, "taken" if taken else "refused", waited * 1000)
    telemetry.event(
        "lock.contended",
        {attrs.LOCK: name, attrs.LOCK_WAIT_MS: round(waited * 1000, 1), attrs.LOCK_TAKEN: taken},
    )


@contextlib.asynccontextmanager
async def lock(
    name: str, *, ttl: float | None = None, wait: float | None = None, renew: bool = False
) -> AsyncIterator[Held]:
    """Hold a lock for the block. Raises Busy when it cannot be taken within `wait`."""
    started = time.perf_counter()
    held = await acquire(name, ttl=ttl, wait=settings.lock_wait if wait is None else wait)
    _note(name, time.perf_counter() - started, held is not None)
    if held is None:
        raise Busy(f"lock {name} is held by another instance")
    async with _holding(held, renew):
        yield held


@contextlib.asynccontextmanager
async def try_lock(
    name: str, *, ttl: float | None = None, renew: bool = False
) -> AsyncIterator[Held | None]:
    """The same, but a taken lock is an answer and not an error: the block gets None."""
    held = await acquire(name, ttl=ttl)
    if held is None:
        yield None
        return
    async with _holding(held, renew):
        yield held
