"""Creating the App and keeping track of where it is installed.

Installations matter for webhooks and checks only — repository work runs on personal tokens.
"""

import logging
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database import SessionLocal
from unsafie.database.repositories.github import (
    GithubAppRepository,
    InstallationRepository,
    RepoRepository,
    UserRepoRepository,
)
from unsafie.github.app import auth
from unsafie.github.client.base import GithubHTTP
from unsafie.github.errors import GithubError

logger = logging.getLogger(__name__)


async def create_from_manifest(code: str) -> dict:
    data = await GithubHTTP().request("POST", f"/app-manifests/{code}/conversions")
    if not data or not data.get("id"):
        raise GithubError("github did not return app credentials")
    async with SessionLocal() as session:
        app = await GithubAppRepository(session).save(
            app_id=int(data["id"]),
            slug=data["slug"],
            name=data.get("name") or data["slug"],
            html_url=data.get("html_url") or f"https://github.com/apps/{data['slug']}",
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            webhook_secret=data.get("webhook_secret") or secrets.token_hex(32),
            private_key=data["pem"],
        )
    logger.info("github app created id=%s slug=%s", app.app_id, app.slug)
    return {"app_id": app.app_id, "slug": app.slug, "name": app.name, "html_url": app.html_url}


async def sync_installation(session: AsyncSession, payload: dict) -> int:
    account = payload.get("account") or {}
    installation_id = int(payload["id"])
    await InstallationRepository(session).upsert(
        installation_id,
        account_id=int(account.get("id") or 0),
        account_login=account.get("login") or "",
        account_type=account.get("type") or "User",
        repository_selection=payload.get("repository_selection") or "all",
    )
    return installation_id


async def sync_repos(session: AsyncSession, installation_id: int, repos: list[dict]) -> list:
    saved = []
    for item in repos:
        owner, _, name = (item.get("full_name") or "").partition("/")
        if not owner or not name:
            continue
        saved.append(
            await RepoRepository(session).upsert(
                installation_id,
                int(item["id"]),
                owner,
                name,
                item.get("default_branch") or "main",
                bool(item.get("private", True)),
            )
        )
    return saved


async def fetch_installation_repos(installation_id: int) -> list[dict]:
    token = await auth.installation_token(installation_id)
    items = (
        await GithubHTTP(token).paginate("/installation/repositories", key="repositories").all(1000)
    )
    return items


async def bind_user(session: AsyncSession, user_id: int, repos: list) -> list[str]:
    aliases = []
    for repo in repos:
        bound = await UserRepoRepository(session).bind(user_id, repo)
        aliases.append(bound.alias)
    return aliases
