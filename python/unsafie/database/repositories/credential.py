import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.credential import AnthropicCredential, CredentialKind

logger = logging.getLogger(__name__)


class CredentialRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def all(self) -> list[AnthropicCredential]:
        return list(
            await self.session.scalars(select(AnthropicCredential).order_by(AnthropicCredential.id))
        )

    async def get(self, credential_id: int) -> AnthropicCredential | None:
        return await self.session.get(AnthropicCredential, credential_id)

    async def create(
        self, kind: CredentialKind, secret: str, label: str | None
    ) -> AnthropicCredential:
        row = AnthropicCredential(kind=kind, secret=secret, label=label)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        logger.info("credential=%s created kind=%s label=%s", row.id, kind, label)
        return row

    async def update(
        self,
        credential_id: int,
        *,
        enabled: bool | None = None,
        label: str | None = None,
        reset: bool = False,
    ) -> AnthropicCredential | None:
        row = await self.get(credential_id)
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

    async def delete(self, credential_id: int) -> bool:
        row = await self.get(credential_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def pick(self, exclude: set[int]) -> AnthropicCredential | None:
        exclude_list = list(exclude) or [0]
        row = await self.session.execute(
            text(
                """
                UPDATE anthropic_credentials SET in_flight = in_flight + 1,
                    uses = uses + 1, last_used_at = now()
                WHERE id = (
                    SELECT id FROM anthropic_credentials
                    WHERE enabled AND (cooldown_until IS NULL OR cooldown_until <= now())
                      AND in_flight < max_concurrent AND id <> ALL(:exclude)
                    ORDER BY (kind = 'oauth') DESC, in_flight, last_used_at NULLS FIRST, id
                    FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING id
                """
            ).bindparams(exclude=exclude_list)
        )
        cred_id = row.scalar()
        await self.session.commit()
        if cred_id is None:
            return None
        return await self.get(int(cred_id))

    async def release(self, credential_id: int) -> None:
        await self.session.execute(
            text(
                "UPDATE anthropic_credentials SET in_flight = greatest(in_flight - 1, 0) "
                "WHERE id = :id"
            ).bindparams(id=credential_id)
        )
        await self.session.commit()

    async def next_cooldown(self) -> datetime | None:
        return await self.session.scalar(
            select(func.min(AnthropicCredential.cooldown_until)).where(
                AnthropicCredential.enabled.is_(True),
                AnthropicCredential.cooldown_until.is_not(None),
            )
        )

    async def succeeded(self, credential_id: int, cost_usd: float | None) -> None:
        row = await self.get(credential_id)
        if row is None:
            return
        row.failures = 0
        row.cooldown_until = None
        row.total_cost_usd += cost_usd or 0.0
        await self.session.commit()

    async def failed(
        self, credential_id: int, *, error: str, cooldown_until: datetime | None, disable: bool
    ) -> None:
        row = await self.get(credential_id)
        if row is None:
            return
        row.failures += 1
        row.last_error = error[:2000]
        row.cooldown_until = cooldown_until
        if disable:
            row.enabled = False
        await self.session.commit()
        logger.warning(
            "credential=%s failed (#%s) cooldown_until=%s disabled=%s",
            credential_id,
            row.failures,
            cooldown_until,
            disable,
        )
