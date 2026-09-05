import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any

import aiohttp

from unsafie.github.errors import Conflict, GithubError, NotFound
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)

TokenProvider = Callable[[], Awaitable[str]]
ACCEPT = "application/vnd.github+json"
RAW = "application/vnd.github.raw"
API_VERSION = "2022-11-28"
TIMEOUT = aiohttp.ClientTimeout(total=60)
RETRIES = 3
PER_PAGE = 100

_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()


async def session() -> aiohttp.ClientSession:
    """One connection pool for the whole process: no TCP+TLS handshake per request."""
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _session_lock:
        if _session is None or _session.closed:
            connector = aiohttp.TCPConnector(
                limit=settings.github_connections,
                limit_per_host=settings.github_connections,
                ttl_dns_cache=300,
            )
            _session = aiohttp.ClientSession(timeout=TIMEOUT, connector=connector)
            logger.info("github http pool opened (limit=%s)", settings.github_connections)
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        logger.info("github http pool closed")
    _session = None


async def run_limited(coros: Iterable[Awaitable], limit: int | None = None) -> list:
    """Run awaitables in parallel, no more than `limit` of them in flight."""
    sem = asyncio.Semaphore(limit or settings.github_concurrency)

    async def run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))


class Paginated:
    def __init__(self, http: "GithubHTTP", path: str, params: dict | None, key: str | None) -> None:
        self.http = http
        self.path = path
        self.params = dict(params or {})
        self.key = key

    async def pages(self, limit: int | None = None) -> AsyncIterator[list]:
        page = 1
        seen = 0
        while True:
            params = {**self.params, "per_page": PER_PAGE, "page": page}
            data = await self.http.request("GET", self.path, params=params)
            items = data.get(self.key, []) if self.key else data
            if not isinstance(items, list) or not items:
                return
            yield items
            seen += len(items)
            if len(items) < PER_PAGE or (limit is not None and seen >= limit):
                return
            page += 1

    async def all(self, limit: int | None = None) -> list:
        out: list = []
        async for chunk in self.pages(limit):
            out.extend(chunk)
            if limit is not None and len(out) >= limit:
                return out[:limit]
        return out


class GithubHTTP:
    def __init__(self, token: TokenProvider | str | None = None) -> None:
        self._token = token

    async def _auth(self) -> str | None:
        if self._token is None:
            return None
        if isinstance(self._token, str):
            return self._token
        return await self._token()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
        accept: str = ACCEPT,
        raw: bool = False,
        allow_404: bool = False,
    ) -> Any:
        url = path if path.startswith("http") else f"{settings.github_api_url}{path}"
        headers = {"Accept": accept, "X-GitHub-Api-Version": API_VERSION, "User-Agent": "unsafie"}
        token = await self._auth()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        started = time.perf_counter()
        http = await session()
        for attempt in range(1, RETRIES + 1):
            async with http.request(
                method, url, headers=headers, params=params, json=json_body
            ) as r:
                body = await r.read()
                ms = (time.perf_counter() - started) * 1000
                logger.info("github %s %s -> %s (%.0fms)", method, url, r.status, ms)
                if r.status == 404 and allow_404:
                    return None
                if r.status in (403, 429) and _rate_limited(r.headers, body):
                    delay = _retry_delay(r.headers, attempt)
                    if attempt < RETRIES and delay <= 60:
                        logger.warning("github rate limited, sleeping %ss", delay)
                        await asyncio.sleep(delay)
                        continue
                if r.status >= 400:
                    raise _error(r.status, body, method, url)
                if raw:
                    return body
                if not body:
                    return None
                try:
                    return json.loads(body)
                except ValueError:
                    return body.decode(errors="replace")
        raise GithubError("github: retries exhausted")

    def paginate(self, path: str, params: dict | None = None, key: str | None = None) -> Paginated:
        return Paginated(self, path, params, key)

    async def graphql(self, query: str, variables: dict | None = None) -> Any:
        data = await self.request(
            "POST",
            f"{settings.github_api_url}/graphql",
            json_body={"query": query, "variables": variables or {}},
        )
        if isinstance(data, dict) and data.get("errors"):
            raise GithubError("graphql: " + "; ".join(e.get("message", "") for e in data["errors"]))
        return (data or {}).get("data")


def _rate_limited(headers, body: bytes) -> bool:
    if headers.get("x-ratelimit-remaining") == "0" or headers.get("retry-after"):
        return True
    return b"rate limit" in body.lower() or b"secondary rate" in body.lower()


def _retry_delay(headers, attempt: int) -> float:
    if (retry_after := headers.get("retry-after")) and retry_after.isdigit():
        return float(retry_after)
    if reset := headers.get("x-ratelimit-reset"):
        try:
            return max(0.0, float(reset) - time.time()) + 1
        except ValueError:
            pass
    return float(2**attempt)


def _error(status: int, body: bytes, method: str, url: str) -> GithubError:
    try:
        data = json.loads(body)
        message = data.get("message") or ""
        if errors := data.get("errors"):
            details = "; ".join(
                e.get("message") or f"{e.get('field', '')} {e.get('code', '')}".strip()
                for e in errors
                if isinstance(e, dict)
            )
            if details:
                message = f"{message} ({details})"
    except ValueError:
        message = short(body.decode(errors="replace"), 300)
    where = f"{method} {url.replace(settings.github_api_url, '')}"
    if status == 404:
        return NotFound(f"not found: {where}. {message}")
    if status in (409, 422):
        return Conflict(f"github refused ({status}) {where}: {message}")
    if status in (401, 403):
        return GithubError(
            f"github denied access ({status}) {where}: {message}. "
            "The App may lack permission on this repository, or it is not installed there."
        )
    return GithubError(f"github error {status} {where}: {message}")


http = GithubHTTP()
