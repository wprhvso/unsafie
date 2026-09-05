import logging

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.agent.tools.base import ToolContext
from unsafie.database import SessionLocal
from unsafie.database.models.github_account import GithubAccount
from unsafie.database.repositories.github import GithubAccountRepository, InstallationRepository
from unsafie.github import workspace
from unsafie.github.app import auth
from unsafie.github.client.user import UserClient
from unsafie.github.errors import UserAuthRequired
from unsafie.github.workspace import Session

logger = logging.getLogger(__name__)

SERVER = "gh"


async def session_for(ctx: ToolContext, args: dict) -> Session:
    return await workspace.open_session(ctx.user_id, args.get("repo"), args.get("branch"))


async def accounts_of(user_id: int) -> list[GithubAccount]:
    async with SessionLocal() as session:
        return await GithubAccountRepository(session).for_user(user_id)


async def account_for(user_id: int, login: str | None) -> GithubAccount:
    rows = await accounts_of(user_id)
    if not rows:
        raise UserAuthRequired()
    if login:
        for row in rows:
            if row.login.lower() == login.lower():
                return row
        known = ", ".join(r.login for r in rows)
        raise UserAuthRequired(f"{login} (connected: {known})")
    return rows[0]


async def user_client(user_id: int, login: str | None = None) -> UserClient:
    account = await account_for(user_id, login)
    return UserClient(auth.user_provider(account), account.login)


async def each_user_client(user_id: int):
    """Yield (client, error) for every connected account; a dead account does not kill the rest."""
    for account in await accounts_of(user_id):
        try:
            await auth.user_token(account)
        except UserAuthRequired as e:
            yield None, (account.login, str(e))
            continue
        yield UserClient(auth.user_provider(account), account.login), None


async def gh_available(session: AsyncSession, ctx: ToolContext) -> bool:
    if not await auth.app_configured():
        return False
    accounts = await GithubAccountRepository(session).for_user(ctx.user_id)
    return bool(accounts)


async def gh_context(session: AsyncSession, ctx: ToolContext) -> str:
    bound = await workspace.repos_of(ctx.user_id)
    accounts = await GithubAccountRepository(session).for_user(ctx.user_id)
    if not bound:
        return (
            "GitHub: accounts connected ("
            + ", ".join(a.login for a in accounts)
            + "), but no repositories are available — the app is not installed on any."
        )
    installations = {i.id: i for i in await InstallationRepository(session).for_user(ctx.user_id)}
    by_account: dict[str, list[str]] = {}
    for binding, repo in bound:
        owner = installations.get(repo.installation_id)
        key = owner.account_login if owner else repo.owner
        line = f"{repo.full} ({repo.default_branch}) as `{binding.alias}`"
        by_account.setdefault(key, []).append(line)
    parts = ["GitHub repositories:"]
    for account, lines in by_account.items():
        parts.append(f"  {account}: " + "; ".join(lines))
    parts.append(
        "  Repository tools take repo= as an alias or owner/name; the default is the only repo."
    )
    return "\n".join(parts)
