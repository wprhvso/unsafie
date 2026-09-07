import logging
import time

import jwt

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.models.github_app import GithubApp
from unsafie.database.repositories.github import GithubAppRepository
from unsafie.github.client.base import session as http_session
from unsafie.github.errors import AppNotInstalled, GithubError
from unsafie.settings import settings

logger = logging.getLogger(__name__)

JWT_TTL = 540


def token_key(installation_id: int) -> str:
    return cluster.key("installation", installation_id, "token")


async def load_app() -> GithubApp:
    async with SessionLocal() as session:
        app = await GithubAppRepository(session).get()
    if app is None:
        raise AppNotInstalled
    return app


async def app_configured() -> bool:
    async with SessionLocal() as session:
        return await GithubAppRepository(session).get() is not None


def app_jwt(app: GithubApp) -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + JWT_TTL, "iss": str(app.app_id)}
    return jwt.encode(payload, app.private_key, algorithm="RS256")


async def forget_installation(installation_id: int) -> None:
    await cluster.client().delete(token_key(installation_id))
    logger.info("installation=%s token forgotten", installation_id)


async def _as_app(method: str, path: str) -> tuple[int, dict | list]:
    app = await load_app()
    headers = {
        "Authorization": f"Bearer {app_jwt(app)}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "unsafie",
    }
    http = await http_session()
    async with http.request(method, f"{settings.github_api_url}{path}", headers=headers) as r:
        return r.status, await r.json(content_type=None)


async def installation_token(installation_id: int) -> str:
    cached = await cluster.client().get(token_key(installation_id))
    if cached:
        return cached
    status, data = await _as_app("POST", f"/app/installations/{installation_id}/access_tokens")
    if status >= 400 or not isinstance(data, dict):
        message = data.get("message") if isinstance(data, dict) else data
        raise GithubError(
            f"could not get an installation token ({status}): {message}. "
            "The App may have been removed from this account."
        )
    token = data["token"]
    await cluster.client().set(
        token_key(installation_id), token, px=int(settings.installation_token_ttl * 1000)
    )
    logger.info("installation=%s token issued", installation_id)
    return token


def installation_provider(installation_id: int):
    async def provider() -> str:
        return await installation_token(installation_id)

    return provider


async def app_installations() -> list[dict]:
    status, data = await _as_app("GET", "/app/installations?per_page=100")
    if status >= 400 or not isinstance(data, list):
        message = data.get("message") if isinstance(data, dict) else data
        raise GithubError(f"could not list app installations ({status}): {message}")
    return data
