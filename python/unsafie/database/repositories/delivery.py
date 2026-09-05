import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.webhook_delivery import WebhookDelivery

logger = logging.getLogger(__name__)


class DeliveryRepository:
    def __init__(self, session: AsyncSession):
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

    async def mark_stale(self) -> int:
        rows = list(
            await self.session.scalars(
                select(WebhookDelivery).where(WebhookDelivery.processed_at.is_(None))
            )
        )
        for row in rows:
            row.processed_at = datetime.now(UTC)
            row.error = "interrupted by restart"
        await self.session.commit()
        return len(rows)

    async def purge(self, keep_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=keep_days)
        res = await self.session.execute(
            delete(WebhookDelivery).where(WebhookDelivery.received_at < cutoff)
        )
        await self.session.commit()
        return res.rowcount or 0

    async def page(
        self, offset: int = 0, limit: int = 50, event: str | None = None, errors_only: bool = False
    ) -> tuple[list[WebhookDelivery], int]:
        cond = []
        if event:
            cond.append(WebhookDelivery.event == event)
        if errors_only:
            cond.append(WebhookDelivery.error.is_not(None))
        total = (
            await self.session.scalar(
                select(func.count()).select_from(WebhookDelivery).where(*cond)
            )
            or 0
        )
        rows = await self.session.scalars(
            select(WebhookDelivery)
            .where(*cond)
            .order_by(WebhookDelivery.received_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows), int(total)
