import logging

from unsafie.agent.tools.base import ToolContext, guarded, json_result, schema
from unsafie.agent.tools.gh.context import SERVER, accounts_of
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import InstallationRepository, UserRepoRepository

logger = logging.getLogger(__name__)


@register(
    SERVER,
    "gh_accounts",
    "The whole GitHub picture for this user: the tokens connected, the repositories available "
    "with their short aliases, and where the App is installed (that is what makes webhook "
    "subscriptions and checks work). Use it to find out what repo= values exist.",
    schema([]),
)
@guarded
async def gh_accounts(ctx: ToolContext, args: dict) -> dict:
    accounts = await accounts_of(ctx.user_id)
    async with SessionLocal() as session:
        bound = await UserRepoRepository(session).for_user(ctx.user_id)
        installations = await InstallationRepository(session).for_user(ctx.user_id)
    installed = {i.id for i in installations}
    repos = [
        {
            "full_name": repo.full,
            "alias": binding.alias,
            "default_branch": repo.default_branch,
            "private": repo.private,
            "events": repo.installation_id in installed,
        }
        for binding, repo in bound
    ]
    if not accounts:
        return json_result(
            {
                "accounts": [],
                "repos": repos,
                "hint": "the user has no GitHub token; ask them to run /gh <token>",
            }
        )
    return json_result(
        {
            "accounts": [
                {
                    "login": a.login,
                    "token": bool(a.token),
                    "scopes": a.scopes or "fine-grained or unknown",
                }
                for a in accounts
            ],
            "app_installations": [
                {
                    "id": i.id,
                    "account": i.account_login,
                    "type": i.account_type,
                    "selection": i.repository_selection,
                    "suspended": i.suspended,
                }
                for i in installations
            ],
            "repos": repos,
        }
    )
