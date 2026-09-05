import logging

from unsafie.agent.tools.base import ToolContext, guarded, json_result, schema
from unsafie.agent.tools.gh.context import SERVER, accounts_of
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import (
    InstallationRepository,
    RepoRepository,
    UserRepoRepository,
)

logger = logging.getLogger(__name__)


@register(
    SERVER,
    "gh_accounts",
    "The whole GitHub picture for this user: connected accounts, app installations under them, and "
    "the repositories available with their short aliases. Use it to find out what repo= values exist.",
    schema([]),
)
@guarded
async def gh_accounts(ctx: ToolContext, args: dict) -> dict:
    accounts = await accounts_of(ctx.user_id)
    async with SessionLocal() as session:
        installations = InstallationRepository(session)
        repos = RepoRepository(session)
        aliases = {
            binding.repo_id: binding.alias
            for binding, _ in await UserRepoRepository(session).for_user(ctx.user_id)
        }
        out = []
        for account in accounts:
            entry = {"login": account.login, "installations": []}
            for installation in await installations.for_account(account.id):
                items = []
                for repo in await repos.for_installation(installation.id):
                    items.append(
                        {
                            "full_name": repo.full,
                            "alias": aliases.get(repo.id),
                            "default_branch": repo.default_branch,
                            "private": repo.private,
                        }
                    )
                entry["installations"].append(
                    {
                        "id": installation.id,
                        "account": installation.account_login,
                        "type": installation.account_type,
                        "selection": installation.repository_selection,
                        "suspended": installation.suspended,
                        "repos": items,
                    }
                )
            out.append(entry)
    if not out:
        return json_result(
            {"accounts": [], "hint": "the user has not connected GitHub; ask them to run /gh"}
        )
    return json_result({"accounts": out})
