from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from unsafie.api.schemas.models import DayPointRead, OverviewRead, PeriodRead
from unsafie.database import SessionLocal
from unsafie.database.models.bot import Bot
from unsafie.database.models.installation import Installation
from unsafie.database.models.opal_session import OpalSession
from unsafie.database.models.repo import Repo
from unsafie.database.models.scheduled_task import ScheduledTask
from unsafie.database.models.ssh_host import SshHost
from unsafie.database.models.ssh_watch import SshWatch
from unsafie.database.models.subscription import GithubSubscription
from unsafie.database.models.webhook_delivery import WebhookDelivery
from unsafie.database.repositories.bot import BotRepository
from unsafie.database.repositories.github import GithubAppRepository
from unsafie.database.repositories.segment import SegmentRepository
from unsafie.database.repositories.stats import StatsRepository
from unsafie.presence import instances
from unsafie.telegram import poller

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
        polled = await poller.polled_by(await BotRepository(session).ids())
        alive = await instances()
        data = OverviewRead(
            users=counts["users"],
            chats=counts["chats"],
            bots=await _count(session, Bot),
            bots_running=sum(1 for by in polled.values() if by),
            running_turns=counts["running_turns"],
            credentials=counts["credentials"],
            credentials_total=await _count(session, OpalSession),
            repos=await _count(session, Repo),
            installations=await _count(session, Installation),
            subscriptions=await _count(session, GithubSubscription),
            schedules=await _count(session, ScheduledTask),
            watches=await _count(session, SshWatch),
            watches_alerting=await _count(session, SshWatch, SshWatch.alerting.is_(True)),
            ssh_hosts=await _count(session, SshHost),
            instances=len(alive),
            ssh_connections=sum(int(i.get("ssh_connections") or 0) for i in alive),
            deliveries_pending=await _count(
                session, WebhookDelivery, WebhookDelivery.processed_at.is_(None)
            ),
            deliveries_failed=await _count(
                session, WebhookDelivery, WebhookDelivery.error.is_not(None)
            ),
            history_bytes=await SegmentRepository(session).total_bytes(),
            github_app=app.slug if app else None,
            day=PeriodRead(**(await stats.period(now - timedelta(days=1))).__dict__),
            week=PeriodRead(**(await stats.period(now - timedelta(days=7))).__dict__),
            month=PeriodRead(**(await stats.period(now - timedelta(days=30))).__dict__),
            daily=[DayPointRead(**p.__dict__) for p in await stats.daily(30)],
        )
    return data
