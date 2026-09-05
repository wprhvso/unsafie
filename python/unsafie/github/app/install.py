import logging
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database import SessionLocal
from unsafie.database.models.github_account import GithubAccount
from unsafie.database.repositories.github import (
    GithubAccountRepository,
    GithubAppRepository,
    InstallationRepository,
    RepoRepository,
    UserRepoRepository,
)
from unsafie.database.repositories.user import UserRepository
from unsafie.github.app import auth
from unsafie.github.client.base import GithubHTTP
from unsafie.github.client.user import UserClient
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


async def link_account(account: GithubAccount) -> list[int]:
    client = UserClient(auth.user_provider(account), account.login)
    installations = await client.installations()
    ids: list[int] = []
    async with SessionLocal() as session:
        for item in installations:
            installation_id = await sync_installation(session, item)
            await InstallationRepository(session).link_account(installation_id, account.id)
            ids.append(installation_id)
    for installation_id in ids:
        try:
            repos = await fetch_installation_repos(installation_id)
        except GithubError as e:
            logger.warning("installation=%s repo sync failed: %s", installation_id, e)
            continue
        async with SessionLocal() as session:
            saved = await sync_repos(session, installation_id, repos)
            await bind_user(session, account.user_id, saved)
    logger.info("account=%s (%s) linked installations=%s", account.id, account.login, ids)
    return ids


async def connect_user(user_id: int, code: str) -> GithubAccount:
    data = await auth.exchange_code(code)
    token = data["access_token"]
    me = await UserClient(token).me()
    async with SessionLocal() as session:
        await UserRepository(session).get_or_create(user_id)
        account = await GithubAccountRepository(session).upsert(
            user_id,
            int(me["id"]),
            me["login"],
            token=token,
            token_expires=auth._expires(data, "expires_in"),
            refresh_token=data.get("refresh_token"),
            refresh_expires=auth._expires(data, "refresh_token_expires_in"),
        )
    await link_account(account)
    return account
