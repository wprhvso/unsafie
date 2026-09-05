import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.database import SessionLocal
from unsafie.database.repositories.github import GithubAccountRepository, InstallationRepository
from unsafie.database.repositories.oauth_state import OAuthStateRepository
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.github import workspace
from unsafie.github.app import auth, manifest
from unsafie.github.errors import GithubError
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


async def _status(user_id: int, locale: str) -> str:
    async with SessionLocal() as session:
        accounts = await GithubAccountRepository(session).for_user(user_id)
        installations = await InstallationRepository(session).for_user(user_id)
    if not accounts:
        return t("github-not-connected", locale)
    bound = await workspace.repos_of(user_id)
    lines = [t("github-accounts", locale, logins=", ".join(a.login for a in accounts))]
    for installation in installations:
        suffix = t("github-suspended", locale) if installation.suspended else ""
        lines.append(
            f"· {installation.account_login} ({installation.repository_selection}){suffix}"
        )
    if bound:
        lines.append(t("github-repos", locale, n=len(bound)))
        lines += [f"· {repo.full} → `{binding.alias}`" for binding, repo in bound[:30]]
    else:
        lines.append(t("github-no-repos", locale))
    return "\n".join(lines)


def build_gh_router() -> Router:
    router = Router()

    @router.message(Command("gh"))
    async def gh_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        arg = (command.args or "").strip().lower()
        if not await auth.app_configured():
            await answer(message, bot_id, t("github-app-missing", locale))
            return
        if arg in ("add", "login", "connect", ""):
            if arg == "" and (await _has_accounts(user_id)):
                await answer(message, bot_id, await _status(user_id, locale))
                return
            async with SessionLocal() as session:
                await UserRepository(session).get_or_create(user_id)
                state = await OAuthStateRepository(session).issue(user_id, bot_id, message.chat.id)
            url = await auth.authorize_url(state)
            await answer(message, bot_id, t("github-connect", locale, url=url))
            return
        if arg in ("install", "repos"):
            try:
                app = await auth.load_app()
            except GithubError as e:
                await answer(message, bot_id, str(e))
                return
            await answer(
                message, bot_id, t("github-install", locale, url=manifest.install_url(app.slug))
            )
            return
        if arg.startswith("rm ") or arg.startswith("remove "):
            login = arg.split(maxsplit=1)[1].strip()
            async with SessionLocal() as session:
                accounts = GithubAccountRepository(session)
                found = await accounts.by_login(user_id, login)
                if found is None:
                    await answer(message, bot_id, t("github-no-account", locale, login=login))
                    return
                await accounts.remove(user_id, found.id)
            await answer(message, bot_id, t("github-removed", locale, login=login))
            return
        await answer(message, bot_id, t("github-usage", locale))

    return router


async def _has_accounts(user_id: int) -> bool:
    async with SessionLocal() as session:
        return bool(await GithubAccountRepository(session).for_user(user_id))
