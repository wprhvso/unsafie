import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.database import SessionLocal
from unsafie.database.repositories.github import InstallationRepository
from unsafie.fluent import t
from unsafie.github import pat, workspace
from unsafie.github.app import auth, manifest
from unsafie.github.errors import GithubError
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)

SHOWN_REPOS = 30


async def _status(user_id: int, locale: str) -> str:
    accounts = await pat.accounts_of(user_id)
    if not accounts:
        return t("github-not-connected", locale)
    async with SessionLocal() as session:
        installations = await InstallationRepository(session).for_user(user_id)
    lines = [t("github-accounts", locale, logins=", ".join(a.login for a in accounts))]
    for account in accounts:
        if not account.token:
            lines.append(t("github-no-token", locale, login=account.login))
        elif account.scopes:
            lines.append(f"· {account.login}: {account.scopes}")
    for installation in installations:
        suffix = t("github-suspended", locale) if installation.suspended else ""
        lines.append(
            f"· app: {installation.account_login} ({installation.repository_selection}){suffix}"
        )
    bound = await workspace.repos_of(user_id)
    if bound:
        lines.append(t("github-repos", locale, n=len(bound)))
        lines += [f"· {repo.full} → `{binding.alias}`" for binding, repo in bound[:SHOWN_REPOS]]
        if len(bound) > SHOWN_REPOS:
            lines.append(t("github-repos-more", locale, n=len(bound) - SHOWN_REPOS))
    else:
        lines.append(t("github-no-repos", locale))
    return "\n".join(lines)


async def _connect(message: Message, bot_id: int, user_id: int, locale: str, token: str) -> None:
    account, scopes = await pat.save(user_id, token)
    try:
        await message.delete()
    except Exception as e:  # the token stays in the chat if the bot may not delete messages
        logger.info("could not delete the message with the token: %s", e)
    repos = await pat.sync(account)
    installations = await pat.link_installations(account)
    lines = [
        t(
            "github-token-saved",
            locale,
            login=account.login,
            n=len(repos),
            apps=len(installations),
        )
    ]
    if missing := pat.missing_scopes(scopes):
        lines.append(t("github-token-scopes", locale, scopes=", ".join(missing)))
    await answer(message, bot_id, "\n".join(lines))


def build_gh_router() -> Router:
    router = Router()

    @router.message(Command("gh"))
    async def gh_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        parts = (command.args or "").split()
        action = parts[0].lower() if parts else ""
        try:
            if not parts:
                await answer(message, bot_id, await _status(user_id, locale))
                return
            if pat.looks_like_token(parts[0]):
                await _connect(message, bot_id, user_id, locale, parts[0])
                return
            if action in ("sync", "refresh"):
                account = await pat.require_account(user_id)
                repos = await pat.sync(account)
                await pat.link_installations(account)
                await answer(message, bot_id, t("github-synced", locale, n=len(repos)))
                return
            if action == "add":
                if len(parts) < 2:
                    await answer(message, bot_id, t("github-usage", locale))
                    return
                repo, alias = await pat.add(user_id, parts[1], parts[2] if len(parts) > 2 else None)
                await answer(
                    message, bot_id, t("github-added", locale, repo=repo.full, alias=alias)
                )
                return
            if action in ("app", "install", "repos"):
                app = await auth.load_app()
                await answer(
                    message, bot_id, t("github-install", locale, url=manifest.install_url(app.slug))
                )
                return
            if action in ("rm", "remove", "logout"):
                if len(parts) < 2:
                    await answer(message, bot_id, t("github-usage", locale))
                    return
                if await pat.forget(user_id, parts[1]) is None:
                    await answer(message, bot_id, t("github-no-account", locale, login=parts[1]))
                    return
                await answer(message, bot_id, t("github-removed", locale, login=parts[1]))
                return
        except GithubError as e:
            await answer(message, bot_id, str(e))
            return
        await answer(message, bot_id, t("github-usage", locale))

    return router
