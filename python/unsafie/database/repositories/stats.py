from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.chat import Chat
from unsafie.database.models.credential import AnthropicCredential
from unsafie.database.models.turn import Turn, TurnStatus
from unsafie.database.models.user import User


@dataclass(frozen=True)
class Period:
    turns: int
    failed: int
    cost_usd: float
    charge: int


@dataclass(frozen=True)
class DayPoint:
    day: str
    turns: int
    cost_usd: float
    charge: int


class StatsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def period(self, since: datetime) -> Period:
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(Turn.status == TurnStatus.FAILED),
                    func.coalesce(func.sum(Turn.cost_usd), 0.0),
                    func.coalesce(func.sum(Turn.charge), 0),
                ).where(Turn.created_at >= since)
            )
        ).one()
        return Period(int(row[0]), int(row[1]), float(row[2]), int(row[3]))

    async def daily(self, days: int) -> list[DayPoint]:
        since = datetime.now(UTC) - timedelta(days=days)
        day = func.date_trunc("day", Turn.created_at)
        rows = (
            await self.session.execute(
                select(
                    day,
                    func.count(),
                    func.coalesce(func.sum(Turn.cost_usd), 0.0),
                    func.coalesce(func.sum(Turn.charge), 0),
                )
                .where(Turn.created_at >= since)
                .group_by(day)
                .order_by(day)
            )
        ).all()
        return [
            DayPoint(r[0].strftime("%Y-%m-%d"), int(r[1]), float(r[2]), int(r[3])) for r in rows
        ]

    async def top_chats(
        self, since: datetime, limit: int = 10
    ) -> list[tuple[int, int, int, float]]:
        rows = (
            await self.session.execute(
                select(
                    Turn.bot_id,
                    Turn.chat_id,
                    func.count(),
                    func.coalesce(func.sum(Turn.cost_usd), 0.0),
                )
                .where(Turn.created_at >= since)
                .group_by(Turn.bot_id, Turn.chat_id)
                .order_by(func.sum(Turn.cost_usd).desc().nulls_last())
                .limit(limit)
            )
        ).all()
        return [(int(r[0]), int(r[1]), int(r[2]), float(r[3])) for r in rows]

    async def by_credential(self, since: datetime) -> list[tuple[int | None, int, float]]:
        rows = (
            await self.session.execute(
                select(
                    Turn.credential_id, func.count(), func.coalesce(func.sum(Turn.cost_usd), 0.0)
                )
                .where(Turn.created_at >= since)
                .group_by(Turn.credential_id)
            )
        ).all()
        return [(r[0], int(r[1]), float(r[2])) for r in rows]

    async def counts(self) -> dict[str, int]:
        users = await self.session.scalar(select(func.count()).select_from(User)) or 0
        chats = await self.session.scalar(select(func.count()).select_from(Chat)) or 0
        running = (
            await self.session.scalar(
                select(func.count()).select_from(Turn).where(Turn.status == TurnStatus.RUNNING)
            )
            or 0
        )
        creds = (
            await self.session.scalar(
                select(func.count())
                .select_from(AnthropicCredential)
                .where(AnthropicCredential.enabled.is_(True))
            )
            or 0
        )
        return {
            "users": int(users),
            "chats": int(chats),
            "running_turns": int(running),
            "credentials": int(creds),
        }
