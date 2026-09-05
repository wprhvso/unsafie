import asyncio
import logging

from sqlalchemy import select

from unsafie.database import SessionLocal
from unsafie.database.models.github_account import GithubAccount
from unsafie.database.models.installation import InstallationAccount
from unsafie.database.models.response import ResponseKind
from unsafie.database.repositories.github import (
    GithubAccountRepository,
    InstallationRepository,
    RepoRepository,
)
from unsafie.database.repositories.subscription import SubscriptionRepository
from unsafie.github import subscriptions
from unsafie.github.app import auth, install
from unsafie.github.webhooks import deliveries
from unsafie.github.webhooks import events as fmt
from unsafie.telegram import sender
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)

LIFECYCLE = {"installation", "installation_repositories", "github_app_authorization"}


async def handle(delivery_id: str, event: str, payload: dict) -> None:
    if not await deliveries.accept(delivery_id, event, payload):
        return
    asyncio.create_task(_process(delivery_id, event, payload), name=f"webhook:{delivery_id}")


async def _process(delivery_id: str, event: str, payload: dict) -> None:
    notified = 0
    error: str | None = None
    try:
        if event in LIFECYCLE:
            await _lifecycle(event, payload)
        else:
            notified = await _notify(event, payload)
    except Exception as e:
        logger.exception("delivery=%s %s failed", delivery_id, event)
        error = str(e)
    await deliveries.done(delivery_id, notified, error)


async def _lifecycle(event: str, payload: dict) -> None:
    action = payload.get("action")
    data = payload.get("installation") or {}
    installation_id = int(data.get("id") or 0)
    if not installation_id:
        return
    async with SessionLocal() as session:
        repos_repo = RepoRepository(session)
        installations = InstallationRepository(session)
        if event == "installation":
            if action in ("deleted", "suspend"):
                auth.forget_installation(installation_id)
                await installations.set_suspended(installation_id, True)
                logger.info("installation=%s suspended (%s)", installation_id, action)
                return
            await install.sync_installation(session, data)
            if action == "unsuspend":
                await installations.set_suspended(installation_id, False)
            saved = await install.sync_repos(
                session, installation_id, payload.get("repositories") or []
            )
            await _bind_all(session, installation_id, saved)
            return
        if event == "installation_repositories":
            await install.sync_installation(session, data)
            added = await install.sync_repos(
                session, installation_id, payload.get("repositories_added") or []
            )
            await _bind_all(session, installation_id, added)
            for item in payload.get("repositories_removed") or []:
                await repos_repo.delete_by_github_id(int(item["id"]))
            logger.info(
                "installation=%s repos +%s -%s",
                installation_id,
                len(added),
                len(payload.get("repositories_removed") or []),
            )


async def _bind_all(session, installation_id: int, repos: list) -> None:
    if not repos:
        return
    users = await _users_of(session, installation_id)
    for user_id in users:
        await install.bind_user(session, user_id, repos)


async def _users_of(session, installation_id: int) -> list[int]:
    rows = await session.scalars(
        select(GithubAccount.user_id)
        .join(InstallationAccount, InstallationAccount.github_account_id == GithubAccount.id)
        .where(InstallationAccount.installation_id == installation_id)
        .distinct()
    )
    return list(rows)


async def _notify(event: str, payload: dict) -> int:
    full_name = (payload.get("repository") or {}).get("full_name") or ""
    owner, _, name = full_name.partition("/")
    if not owner:
        return 0
    async with SessionLocal() as session:
        repo = await RepoRepository(session).by_full_name(owner, name)
        if repo is None:
            logger.info("webhook for unknown repo %s, ignored", full_name)
            return 0
        subs = await SubscriptionRepository(session).for_repo(repo.id)
        if not subs:
            return 0
        logins_by_user: dict[int, set[str]] = {}
        for sub in subs:
            if sub.user_id not in logins_by_user:
                logins_by_user[sub.user_id] = await GithubAccountRepository(session).logins(
                    sub.user_id
                )
    sent = 0
    for sub in subs:
        logins = logins_by_user.get(sub.user_id, set())
        text: str | None = None
        if sub.kind == "mentions":
            login = subscriptions.mentioned(payload, logins)
            if login:
                text = fmt.render_mention(event, payload, login)
        elif subscriptions.matches(sub, event, payload, logins):
            text = fmt.render(event, payload)
        if not text:
            continue
        bot = manager.bot(sub.bot_id)
        if bot is None:
            logger.warning("sub=%s: bot %s is not running", sub.id, sub.bot_id)
            continue
        try:
            await sender.send(
                bot,
                bot_id=sub.bot_id,
                chat_id=sub.chat_id,
                markdown=text,
                kind=ResponseKind.SYSTEM,
                silent=True,
            )
            sent += 1
        except Exception:
            logger.exception("sub=%s: notification failed", sub.id)
    if sent:
        logger.info("%s %s -> %s notification(s)", full_name, event, sent)
    return sent
