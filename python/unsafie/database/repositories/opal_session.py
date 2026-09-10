import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.opal_session import OpalSession

logger = logging.getLogger(__name__)


class OpalSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def all(self) -> list[OpalSession]:
        return list(
            await self.session.scalars(select(OpalSession).order_by(OpalSession.id)),
        )

    async def get(self, session_id: int) -> OpalSession | None:
        return await self.session.get(OpalSession, session_id)

    async def create(self, refresh_token: str, label: str | None) -> OpalSession:
        row = OpalSession(refresh_token=refresh_token, label=label)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        logger.info("opal_session=%s created label=%s", row.id, label)
        return row

    async def update(
        self,
        session_id: int,
        *,
        enabled: bool | None = None,
        label: str | None = None,
        reset: bool = False,
    ) -> OpalSession | None:
        row = await self.get(session_id)
        if row is None:
            return None
        if enabled is not None:
            row.enabled = enabled
        if label is not None:
            row.label = label
        if reset:
            row.failures = 0
            row.cooldown_until = None
            row.last_error = None
        await self.session.commit()
        return row

    async def delete(self, session_id: int) -> bool:
        row = await self.get(session_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def pick(self, exclude: set[int] | None = None) -> OpalSession | None:
        now = datetime.now(UTC)
        stmt = (
            select(OpalSession)
            .where(
                OpalSession.enabled.is_(True),
                or_(
                    OpalSession.cooldown_until.is_(None),
                    OpalSession.cooldown_until <= now,
                ),
            )
            .order_by(
                OpalSession.last_used_at.asc().nulls_first(),
                OpalSession.id,
            )
        )
        if exclude:
            stmt = stmt.where(OpalSession.id.not_in(exclude))
        row = await self.session.scalar(stmt.limit(1).with_for_update(skip_locked=True))
        if row is not None:
            row.last_used_at = now
            row.uses += 1
            await self.session.commit()
        return row

    async def next_cooldown(self) -> datetime | None:
        return await self.session.scalar(
            select(func.min(OpalSession.cooldown_until)).where(
                OpalSession.enabled.is_(True),
                OpalSession.cooldown_until.is_not(None),
            ),
        )

    async def succeeded(self, session_id: int) -> None:
        row = await self.get(session_id)
        if row is None:
            return
        row.failures = 0
        row.cooldown_until = None
        await self.session.commit()

    async def failed(
        self, session_id: int, *, error: str, cooldown_until: datetime | None, disable: bool,
    ) -> None:
        row = await self.get(session_id)
        if row is None:
            return
        row.failures += 1
        row.last_error = error[:2000]
        row.cooldown_until = cooldown_until
        if disable:
            row.enabled = False
        await self.session.commit()
        logger.warning(
            "opal_session=%s failed (#%s) cooldown_until=%s disabled=%s",
            session_id,
            row.failures,
            cooldown_until,
            disable,
        )
