from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.chat import Chat
from unsafie.database.models.opal_session import OpalSession
from unsafie.database.models.turn import Turn, TurnStatus
from unsafie.database.models.user import User


@dataclass(frozen=True)
class Period:
    turns: int
    failed: int


@dataclass(frozen=True)
class DayPoint:
    day: str
    turns: int


class StatsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def period(self, since: datetime) -> Period:
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(Turn.status == TurnStatus.FAILED),
                ).where(Turn.created_at >= since)
            )
        ).one()
        return Period(int(row[0]), int(row[1]))

    async def daily(self, days: int) -> list[DayPoint]:
        since = datetime.now(UTC) - timedelta(days=days)
        day = func.date_trunc("day", Turn.created_at)
        rows = (
            await self.session.execute(
                select(
                    day,
                    func.count(),
                )
                .where(Turn.created_at >= since)
                .group_by(day)
                .order_by(day)
            )
        ).all()
        return [
            DayPoint(r[0].strftime("%Y-%m-%d"), int(r[1])) for r in rows
        ]

    async def top_chats(
        self, since: datetime, limit: int = 10
    ) -> list[tuple[int, int, int]]:
        rows = (
            await self.session.execute(
                select(
                    Turn.bot_id,
                    Turn.chat_id,
                    func.count(),
                )
                .where(Turn.created_at >= since)
                .group_by(Turn.bot_id, Turn.chat_id)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
        return [(int(r[0]), int(r[1]), int(r[2])) for r in rows]

    async def by_credential(self, since: datetime) -> list[tuple[int | None, int]]:
        rows = (
            await self.session.execute(
                select(
                    Turn.credential_id, func.count()
                )
                .where(Turn.created_at >= since)
                .group_by(Turn.credential_id)
                .order_by(func.count().desc())
            )
        ).all()
        return [(r[0], int(r[1])) for r in rows]

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
                .select_from(OpalSession)
                .where(OpalSession.enabled.is_(True))
            )
            or 0
        )
        return {
            "users": int(users),
            "chats": int(chats),
            "running_turns": int(running),
            "credentials": int(creds),
        }
