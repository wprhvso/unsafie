from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from unsafie.api.schemas.models import DayPointRead, PeriodRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.stats import StatsRepository

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/daily", response_model=list[DayPointRead])
async def daily(days: int = 30):
    async with SessionLocal() as session:
        rows = await StatsRepository(session).daily(min(days, 365))
    return [DayPointRead(**r.__dict__) for r in rows]


@router.get("/period", response_model=PeriodRead)
async def period(hours: int = 24):
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with SessionLocal() as session:
        return PeriodRead(**(await StatsRepository(session).period(since)).__dict__)


@router.get("/top-chats")
async def top_chats(hours: int = 168, limit: int = 10):
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with SessionLocal() as session:
        rows = await StatsRepository(session).top_chats(since, limit)
    return [{"bot_id": b, "chat_id": c, "turns": n, "cost_usd": cost} for b, c, n, cost in rows]


@router.get("/by-credential")
async def by_credential(hours: int = 168):
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with SessionLocal() as session:
        rows = await StatsRepository(session).by_credential(since)
    return [{"credential_id": c, "turns": n, "cost_usd": cost} for c, n, cost in rows]
