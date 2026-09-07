import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import AsyncIterator, Iterable
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
    pass


class Busy(RuntimeError):
    pass


def key(*parts: str | int) -> str:
    return ":".join([settings.redis_prefix, *(str(p) for p in parts)])


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.password:
        return url
    user = parsed.username or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{user}:«redacted»@{parsed.hostname or ''}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


async def connect() -> Redis:
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
    started = time.perf_counter()
    try:
        await client().ping()
    except (Unavailable, RedisError, OSError) as e:
        return {"status": "down", "error": str(e)[:200]}
    return {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}


@dataclass
class Held:
    name: str
    key: str
    token: str
    ttl: float
    taken_at: float

    @property
    def age(self) -> float:
        return time.monotonic() - self.taken_at

    async def extend(self, ttl: float | None = None) -> bool:
        ms = int((ttl or self.ttl) * 1000)
        return bool(await _extend(keys=[self.key], args=[self.token, ms]))

    async def release(self) -> bool:
        return bool(await _release(keys=[self.key], args=[self.token]))


async def acquire(name: str, *, ttl: float | None = None, wait: float = 0.0) -> Held | None:
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


def holder(token: str | None) -> str | None:
    return token.split(":", 1)[0] if token else None


async def owners(names: Iterable[str]) -> dict[str, str | None]:
    wanted = list(names)
    if not wanted:
        return {}
    values = await client().mget([key("lock", n) for n in wanted])
    return {name: holder(value) for name, value in zip(wanted, values, strict=True)}


async def mark(name: str, value: str, ttl: float) -> None:
    await client().set(key("mark", name), value, px=int(ttl * 1000))


async def marked(name: str) -> str | None:
    return await client().get(key("mark", name))


async def marks(names: Iterable[str]) -> dict[str, str | None]:
    wanted = list(names)
    if not wanted:
        return {}
    values = await client().mget([key("mark", n) for n in wanted])
    return dict(zip(wanted, values, strict=True))


async def _keep(held: Held) -> None:
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
    started = time.perf_counter()
    held = await acquire(name, ttl=ttl, wait=settings.lock_wait if wait is None else wait)
    _note(name, time.perf_counter() - started, held is not None)
    if held is None:
        raise Busy(f"lock {name} is held by another instance")
    async with _holding(held, renew):
        yield held


@contextlib.asynccontextmanager
async def try_lock(
    name: str, *, ttl: float | None = None, wait: float = 0.0, renew: bool = False
) -> AsyncIterator[Held | None]:
    started = time.perf_counter()
    held = await acquire(name, ttl=ttl, wait=wait)
    _note(name, time.perf_counter() - started, held is not None)
    if held is None:
        yield None
        return
    async with _holding(held, renew):
        yield held
