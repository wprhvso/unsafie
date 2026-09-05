from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from unsafie.api.schemas.models import DayPointRead, OverviewRead, PeriodRead
from unsafie.database import SessionLocal
from unsafie.database.models.bot import Bot
from unsafie.database.models.credential import AnthropicCredential
from unsafie.database.models.installation import Installation
from unsafie.database.models.repo import Repo
from unsafie.database.models.scheduled_task import ScheduledTask
from unsafie.database.models.ssh_host import SshHost
from unsafie.database.models.ssh_watch import SshWatch
from unsafie.database.models.subscription import GithubSubscription
from unsafie.database.models.webhook_delivery import WebhookDelivery
from unsafie.database.repositories.github import GithubAppRepository
from unsafie.database.repositories.stats import StatsRepository
from unsafie.ssh.pool import pool
from unsafie.telegram.manager import manager

router = APIRouter(tags=["overview"])


async def _count(session, model, *where) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


@router.get("/overview", response_model=OverviewRead)
async def overview():
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        stats = StatsRepository(session)
        counts = await stats.counts()
        app = await GithubAppRepository(session).get()
        data = OverviewRead(
            users=counts["users"],
            chats=counts["chats"],
            bots=await _count(session, Bot),
            bots_running=len(manager.running_ids()),
            running_turns=counts["running_turns"],
            credentials=counts["credentials"],
            credentials_total=await _count(session, AnthropicCredential),
            repos=await _count(session, Repo),
            installations=await _count(session, Installation),
            subscriptions=await _count(session, GithubSubscription),
            schedules=await _count(session, ScheduledTask),
            watches=await _count(session, SshWatch),
            watches_alerting=await _count(session, SshWatch, SshWatch.alerting.is_(True)),
            ssh_hosts=await _count(session, SshHost),
            ssh_connections=len([s for s in pool.stats() if s["alive"]]),
            deliveries_pending=await _count(
                session, WebhookDelivery, WebhookDelivery.processed_at.is_(None)
            ),
            deliveries_failed=await _count(
                session, WebhookDelivery, WebhookDelivery.error.is_not(None)
            ),
            github_app=app.slug if app else None,
            day=PeriodRead(**(await stats.period(now - timedelta(days=1))).__dict__),
            week=PeriodRead(**(await stats.period(now - timedelta(days=7))).__dict__),
            month=PeriodRead(**(await stats.period(now - timedelta(days=30))).__dict__),
            daily=[DayPointRead(**p.__dict__) for p in await stats.daily(30)],
        )
    return data
