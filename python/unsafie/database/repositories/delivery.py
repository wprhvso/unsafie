from unsafie.log import get_logger
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.webhook_delivery import WebhookDelivery
from unsafie.settings import settings

logger = get_logger(__name__)


class DeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(
        self,
        *,
        delivery_id: str,
        event: str,
        action: str | None,
        installation_id: int | None,
        repo_full_name: str | None,
        sender: str | None,
        payload: dict,
        trace_id: str | None = None,
    ) -> bool:
        stmt = (
            insert(WebhookDelivery)
            .values(
                delivery_id=delivery_id,
                event=event,
                action=action,
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                sender=sender,
                payload=payload,
                trace_id=trace_id,
            )
            .on_conflict_do_nothing(index_elements=[WebhookDelivery.delivery_id])
            .returning(WebhookDelivery.delivery_id)
        )
        stored = await self.session.scalar(stmt)
        await self.session.commit()
        return stored is not None

    async def get(self, delivery_id: str) -> WebhookDelivery | None:
        return await self.session.get(WebhookDelivery, delivery_id)

    async def processed(self, delivery_id: str, notified: int, error: str | None) -> None:
        row = await self.get(delivery_id)
        if row is None:
            return
        row.processed_at = datetime.now(UTC)
        row.notified = notified
        row.error = error[:2000] if error else None
        await self.session.commit()

    async def claim(self, limit: int, lease: float) -> list[WebhookDelivery]:
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=lease)
        rows = list(
            await self.session.scalars(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.processed_at.is_(None),
                    or_(
                        WebhookDelivery.claimed_at.is_(None),
                        WebhookDelivery.claimed_at < cutoff,
                    ),
                )
                .order_by(WebhookDelivery.received_at)
                .limit(limit)
                .with_for_update(skip_locked=True),
            ),
        )
        for row in rows:
            row.claimed_at = now
            row.claimed_by = settings.instance_id
            row.attempts += 1
        await self.session.commit()
        return rows

    async def failed(self, delivery_id: str, error: str, give_up: bool) -> None:
        row = await self.get(delivery_id)
        if row is None:
            return
        row.error = error[:2000]
        row.claimed_at = None if not give_up else row.claimed_at
        if give_up:
            row.processed_at = datetime.now(UTC)
        await self.session.commit()

    async def purge(self, keep_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=keep_days)
        res = await self.session.execute(
            delete(WebhookDelivery).where(WebhookDelivery.received_at < cutoff),
        )
        await self.session.commit()
        return int(getattr(res, "rowcount", 0) or 0)

    async def page(
        self, offset: int = 0, limit: int = 50, event: str | None = None, errors_only: bool = False,
    ) -> tuple[list[WebhookDelivery], int]:
        cond = []
        if event:
            cond.append(WebhookDelivery.event == event)
        if errors_only:
            cond.append(WebhookDelivery.error.is_not(None))
        total = (
            await self.session.scalar(
                select(func.count()).select_from(WebhookDelivery).where(*cond),
            )
            or 0
        )
        rows = await self.session.scalars(
            select(WebhookDelivery)
            .where(*cond)
            .order_by(WebhookDelivery.received_at.desc())
            .offset(offset)
            .limit(limit),
        )
        return list(rows), int(total)
