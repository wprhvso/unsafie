import aiohttp

from unsafie import cluster
from unsafie.errors import OpsError
from unsafie.settings import settings


class OpalError(OpsError):
    pass


class OpalRefreshFailed(OpalError):
    pass


def token_key(session_id: int) -> str:
    return cluster.key("opal", "access", session_id)


async def refresh_access_token(refresh_token: str) -> str:
    headers = {"User-Agent": "unsafie"}
    cookies = {"OAuthRefreshToken": refresh_token}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        try:
            async with http.get(settings.opal_refresh_url, cookies=cookies, headers=headers) as resp:
                if resp.status != 200:
                    msg = f"opal refresh returned HTTP {resp.status}"
                    raise OpalRefreshFailed(msg)
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as e:
            msg = f"opal refresh request failed: {e}"
            raise OpalRefreshFailed(msg) from e

    access_token = data.get("access_token") if isinstance(data, dict) else None
    if not isinstance(access_token, str) or not access_token:
        msg = "opal response missing access_token"
        raise OpalRefreshFailed(msg)
    return access_token


async def get_access_token(session_id: int, refresh_token: str) -> str:
    client = cluster.client()
    key = token_key(session_id)
    cached = await client.get(key)
    if cached:
        return str(cached)
    fresh = await refresh_access_token(refresh_token)
    await client.set(key, fresh, ex=settings.opal_access_ttl)
    return fresh


async def invalidate(session_id: int) -> None:
    await cluster.client().delete(token_key(session_id))
