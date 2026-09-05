import logging
import time
from datetime import UTC, datetime, timedelta

import jwt

from unsafie.database import SessionLocal
from unsafie.database.models.github_account import GithubAccount
from unsafie.database.models.github_app import GithubApp
from unsafie.database.repositories.github import GithubAccountRepository, GithubAppRepository
from unsafie.github.client.base import session as http_session
from unsafie.github.errors import AppNotInstalled, GithubError, UserAuthRequired
from unsafie.settings import settings

logger = logging.getLogger(__name__)

JWT_TTL = 540
INSTALLATION_TTL = timedelta(minutes=50)
REFRESH_MARGIN = timedelta(minutes=5)
TOKEN_URL = "https://github.com/login/oauth/access_token"
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"

_installation_cache: dict[int, tuple[str, datetime]] = {}


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


def forget_installation(installation_id: int) -> None:
    _installation_cache.pop(installation_id, None)


async def installation_token(installation_id: int) -> str:
    cached = _installation_cache.get(installation_id)
    now = datetime.now(UTC)
    if cached and cached[1] > now:
        return cached[0]
    app = await load_app()
    headers = {
        "Authorization": f"Bearer {app_jwt(app)}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "unsafie",
    }
    url = f"{settings.github_api_url}/app/installations/{installation_id}/access_tokens"
    http = await http_session()
    async with http.post(url, headers=headers) as r:
        data = await r.json(content_type=None)
        if r.status >= 400:
            raise GithubError(
                f"could not get an installation token ({r.status}): {data.get('message')}. "
                "The App may have been removed from this account."
            )
    token = data["token"]
    _installation_cache[installation_id] = (token, now + INSTALLATION_TTL)
    logger.info("installation=%s token issued", installation_id)
    return token


def installation_provider(installation_id: int):
    async def provider() -> str:
        return await installation_token(installation_id)

    return provider


async def _exchange(app: GithubApp, payload: dict) -> dict:
    http = await http_session()
    async with http.post(
        TOKEN_URL,
        headers={"Accept": "application/json"},
        data={**payload, "client_id": app.client_id, "client_secret": app.client_secret},
    ) as r:
        data = await r.json(content_type=None)
    if not isinstance(data, dict) or data.get("error") or not data.get("access_token"):
        raise GithubError(f"github oauth: {(data or {}).get('error_description') or data}")
    return data


def _expires(data: dict, key: str) -> datetime | None:
    seconds = data.get(key)
    if not seconds:
        return None
    return datetime.now(UTC) + timedelta(seconds=int(seconds))


async def exchange_code(code: str) -> dict:
    app = await load_app()
    return await _exchange(app, {"code": code, "grant_type": "authorization_code"})


async def user_token(account: GithubAccount) -> str:
    now = datetime.now(UTC)
    if account.token and (
        account.token_expires is None or account.token_expires - REFRESH_MARGIN > now
    ):
        return account.token
    if not account.refresh_token or (account.refresh_expires and account.refresh_expires <= now):
        raise UserAuthRequired(account.login)
    app = await load_app()
    try:
        data = await _exchange(
            app, {"refresh_token": account.refresh_token, "grant_type": "refresh_token"}
        )
    except GithubError as e:
        logger.warning("account=%s refresh failed: %s", account.id, e)
        raise UserAuthRequired(account.login) from None
    async with SessionLocal() as session:
        await GithubAccountRepository(session).set_tokens(
            account.id,
            token=data["access_token"],
            token_expires=_expires(data, "expires_in"),
            refresh_token=data.get("refresh_token") or account.refresh_token,
            refresh_expires=_expires(data, "refresh_token_expires_in"),
        )
    account.token = data["access_token"]
    logger.info("account=%s (%s) token refreshed", account.id, account.login)
    return account.token


def user_provider(account: GithubAccount):
    async def provider() -> str:
        return await user_token(account)

    return provider


async def authorize_url(state: str) -> str:
    app = await load_app()
    from unsafie.github.app.manifest import oauth_url

    return f"{AUTHORIZE_URL}?client_id={app.client_id}&state={state}&redirect_uri={oauth_url()}"
