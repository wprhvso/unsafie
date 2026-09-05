import logging

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.agent.tools.base import ToolContext
from unsafie.database.models.github_account import GithubAccount
from unsafie.database.repositories.github import GithubAccountRepository, InstallationRepository
from unsafie.github import pat, workspace
from unsafie.github.client.user import UserClient
from unsafie.github.errors import UserAuthRequired
from unsafie.github.workspace import Session
from unsafie.settings import settings

logger = logging.getLogger(__name__)

SERVER = "gh"


async def session_for(ctx: ToolContext, args: dict) -> Session:
    return await workspace.open_session(ctx.user_id, args.get("repo"), args.get("branch"))


async def accounts_of(user_id: int) -> list[GithubAccount]:
    return await pat.accounts_of(user_id)


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
    return await pat.user_client(user_id, login)


async def each_user_client(user_id: int):
    """Yield (client, error) for every connected account; a tokenless one does not kill the rest."""
    for account in await accounts_of(user_id):
        if not account.token:
            yield None, (account.login, str(UserAuthRequired(account.login)))
            continue
        yield pat.client(account), None


async def gh_available(session: AsyncSession, ctx: ToolContext) -> bool:
    accounts = await GithubAccountRepository(session).for_user(ctx.user_id)
    return any(a.token for a in accounts)


async def gh_context(session: AsyncSession, ctx: ToolContext) -> str:
    bound = await workspace.repos_of(ctx.user_id)
    accounts = await GithubAccountRepository(session).for_user(ctx.user_id)
    if not bound:
        return (
            "GitHub: token connected ("
            + ", ".join(a.login for a in accounts)
            + "), but no repositories are bound yet — /gh sync or /gh add owner/name."
        )
    installations = {i.id for i in await InstallationRepository(session).for_user(ctx.user_id)}
    limit = settings.github_prompt_repos
    parts = ["GitHub repositories:"]
    for binding, repo in bound[:limit]:
        events = " [events]" if repo.installation_id in installations else ""
        parts.append(f"  {repo.full} ({repo.default_branch}) as `{binding.alias}`{events}")
    if len(bound) > limit:
        parts.append(f"  … and {len(bound) - limit} more, see gh_accounts")
    parts.append(
        "  Repository tools take repo= as an alias or owner/name; the default is the only repo. "
        "[events] means the App is installed there, so webhook subscriptions work."
    )
    return "\n".join(parts)
