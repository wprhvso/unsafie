"""Personal access tokens — the credential the bot works with.

Everything a token can do goes through the token: repositories, issues, pull requests, actions,
search, gists, notifications. The GitHub App is kept only for what no token can do — webhook
delivery and the Checks API — so it is a fallback here, never the entry point.
"""

import logging
import string

from unsafie.database import SessionLocal
from unsafie.database.models.github_account import GithubAccount
from unsafie.database.models.repo import Repo
from unsafie.database.repositories.github import (
    GithubAccountRepository,
    InstallationRepository,
    RepoRepository,
    UserRepoRepository,
)
from unsafie.database.repositories.user import UserRepository
from unsafie.github.app import auth
from unsafie.github.client.base import ACCEPT, API_VERSION, TokenProvider, session
from unsafie.github.client.user import UserClient
from unsafie.github.errors import GithubError, UserAuthRequired
from unsafie.settings import settings

logger = logging.getLogger(__name__)

PREFIXES = ("ghp_", "github_pat_", "gho_", "ghu_", "ghs_", "ghr_")
NEEDED_SCOPES = ("repo",)
NICE_SCOPES = ("workflow", "gist", "notifications", "read:org")


def looks_like_token(value: str) -> bool:
    """A PAT, not a subcommand: either a known prefix or the old 40-char hex form."""
    if value.startswith(PREFIXES):
        return True
    return len(value) == 40 and all(c in string.hexdigits for c in value)


def missing_scopes(scopes: list[str]) -> list[str]:
    """Fine-grained tokens report no scopes at all — nothing to complain about then."""
    if not scopes:
        return []
    return [s for s in NEEDED_SCOPES + NICE_SCOPES if s not in scopes]


async def verify(token: str) -> tuple[dict, list[str]]:
    """Who the token belongs to and which classic scopes it carries (empty for fine-grained)."""
    http = await session()
    headers = {
        "Accept": ACCEPT,
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "unsafie",
        "Authorization": f"Bearer {token}",
    }
    async with http.get(f"{settings.github_api_url}/user", headers=headers) as r:
        data = await r.json(content_type=None)
        if r.status >= 400 or not isinstance(data, dict) or not data.get("login"):
            message = (data or {}).get("message") if isinstance(data, dict) else None
            raise GithubError(f"github rejected the token ({r.status}): {message or 'no /user'}")
        raw = r.headers.get("x-oauth-scopes") or ""
    return data, [s.strip() for s in raw.split(",") if s.strip()]


async def save(user_id: int, token: str) -> tuple[GithubAccount, list[str]]:
    me, scopes = await verify(token)
    async with SessionLocal() as db:
        await UserRepository(db).get_or_create(user_id)
        account = await GithubAccountRepository(db).upsert(
            user_id, int(me["id"]), me["login"], token=token, scopes=", ".join(scopes) or None
        )
    logger.info(
        "user=%s token for %s saved (%s)",
        user_id,
        account.login,
        ", ".join(scopes) or "fine-grained",
    )
    return account, scopes


async def accounts_of(user_id: int) -> list[GithubAccount]:
    async with SessionLocal() as db:
        return await GithubAccountRepository(db).for_user(user_id)


async def account_of(user_id: int, login: str | None = None) -> GithubAccount | None:
    rows = [a for a in await accounts_of(user_id) if a.token]
    if not rows:
        return None
    if login is None:
        return rows[0]
    return next((a for a in rows if a.login.lower() == login.lower()), None)


async def require_account(user_id: int, login: str | None = None) -> GithubAccount:
    account = await account_of(user_id, login)
    if account is None:
        raise UserAuthRequired(login)
    return account


def client(account: GithubAccount) -> UserClient:
    return UserClient(account.token or "", account.login)


async def user_client(user_id: int, login: str | None = None) -> UserClient:
    return client(await require_account(user_id, login))


def provider(user_id: int, login: str | None = None) -> TokenProvider:
    """A lazy token: the account is looked up once per client, not once per request."""
    box: dict[str, str] = {}

    async def resolve() -> str:
        if "token" not in box:
            account = await require_account(user_id, login)
            box["token"] = account.token or ""
        return box["token"]

    return resolve


def app_provider(repo: Repo) -> TokenProvider | None:
    """The App token for this repository, if it happens to be installed there."""
    if not repo.installation_id:
        return None
    return auth.installation_provider(repo.installation_id)


async def token_for(user_id: int, repo: Repo) -> str:
    """A single token for a raw download: the user's, or the App's when there is none."""
    account = await account_of(user_id)
    if account and account.token:
        return account.token
    if repo.installation_id:
        return await auth.installation_token(repo.installation_id)
    raise UserAuthRequired()


async def remember(user_id: int, items: list[dict]) -> list[Repo]:
    """Save repositories seen by a token and give the user a short alias for each."""
    saved: list[Repo] = []
    async with SessionLocal() as db:
        repos = RepoRepository(db)
        bindings = UserRepoRepository(db)
        for item in items:
            owner, _, name = (item.get("full_name") or "").partition("/")
            if not owner or not name:
                continue
            row = await repos.upsert(
                None,
                int(item["id"]),
                owner,
                name,
                item.get("default_branch") or "main",
                bool(item.get("private", True)),
            )
            await bindings.bind(user_id, row)
            saved.append(row)
    return saved


async def sync(account: GithubAccount, limit: int | None = None) -> list[Repo]:
    items = await client(account).repos(limit or settings.github_repo_sync_limit)
    saved = await remember(account.user_id, items)
    logger.info("account=%s (%s) sees %s repo(s)", account.id, account.login, len(saved))
    return saved


async def add(user_id: int, ref: str, alias: str | None = None) -> tuple[Repo, str]:
    """Bind one repository by owner/name — the way to reach someone else's private repo."""
    account = await require_account(user_id)
    owner, _, name = ref.strip().partition("/")
    if not owner or not name:
        raise GithubError(f"expected owner/name, got '{ref}'")
    data = await client(account).repo(owner, name)
    async with SessionLocal() as db:
        row = await RepoRepository(db).upsert(
            None,
            int(data["id"]),
            data["owner"]["login"],
            data["name"],
            data.get("default_branch") or "main",
            bool(data.get("private", True)),
        )
        bound = await UserRepoRepository(db).bind(user_id, row, alias)
    return row, bound.alias


async def link_installations(account: GithubAccount) -> list[int]:
    """Match App installations to the account by login: /user/installations needs an OAuth token."""
    from unsafie.github.app import install

    if not await auth.app_configured():
        return []
    try:
        installations = await auth.app_installations()
    except GithubError as e:
        logger.info("cannot list app installations: %s", e)
        return []
    logins = {account.login.lower()}
    try:
        logins |= {(o.get("login") or "").lower() for o in await client(account).orgs()}
    except GithubError as e:
        logger.info("account=%s org list failed: %s", account.id, e)
    ids: list[int] = []
    async with SessionLocal() as db:
        for item in installations:
            login = ((item.get("account") or {}).get("login") or "").lower()
            if login not in logins:
                continue
            installation_id = await install.sync_installation(db, item)
            await InstallationRepository(db).link_account(installation_id, account.id)
            ids.append(installation_id)
    for installation_id in ids:
        try:
            repos = await install.fetch_installation_repos(installation_id)
        except GithubError as e:
            logger.warning("installation=%s repo sync failed: %s", installation_id, e)
            continue
        async with SessionLocal() as db:
            saved = await install.sync_repos(db, installation_id, repos)
            await install.bind_user(db, account.user_id, saved)
    logger.info("account=%s (%s) linked installations=%s", account.id, account.login, ids)
    return ids


async def forget(user_id: int, login: str) -> GithubAccount | None:
    async with SessionLocal() as db:
        accounts = GithubAccountRepository(db)
        found = await accounts.by_login(user_id, login)
        if found is None:
            return None
        return await accounts.remove(user_id, found.id)
