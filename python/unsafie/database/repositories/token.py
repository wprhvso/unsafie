import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.api_token import ApiToken

logger = logging.getLogger(__name__)


class TokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, **fields) -> ApiToken:
        token = ApiToken(**fields)
        self.session.add(token)
        await self.session.commit()
        await self.session.refresh(token)
        logger.info(
            "user=%s token '%s' issued kind=%s scopes=%s",
            token.user_id,
            token.name,
            token.kind,
            token.scopes,
        )
        return token

    async def by_hash(self, token_hash: str) -> ApiToken | None:
        return await self.session.scalar(
            select(ApiToken).where(ApiToken.token_hash == token_hash, ApiToken.revoked_at.is_(None)),
        )

    async def for_user(self, user_id: int, alive_only: bool = True) -> list[ApiToken]:
        query = select(ApiToken).where(ApiToken.user_id == user_id)
        if alive_only:
            query = query.where(ApiToken.revoked_at.is_(None))
        rows = await self.session.scalars(query.order_by(ApiToken.id.desc()))
        return list(rows)

    async def by_name(self, user_id: int, name: str) -> ApiToken | None:
        return await self.session.scalar(
            select(ApiToken).where(
                ApiToken.user_id == user_id,
                ApiToken.name == name,
                ApiToken.revoked_at.is_(None),
            ),
        )

    async def touch(self, token_id: int) -> None:
        await self.session.execute(
            update(ApiToken).where(ApiToken.id == token_id).values(last_used_at=datetime.now(UTC)),
        )
        await self.session.commit()

    async def revoke(self, user_id: int, name: str) -> bool:
        found = await self.by_name(user_id, name)
        if found is None:
            return False
        found.revoked_at = datetime.now(UTC)
        await self.session.commit()
        logger.info("user=%s token '%s' revoked", user_id, name)
        return True

    async def revoke_machine(self, machine: str) -> int:
        result = await self.session.execute(
            update(ApiToken)
            .where(ApiToken.machine == machine, ApiToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC)),
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
