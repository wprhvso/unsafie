import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.response import Response
from unsafie.database.models.share import Share
from unsafie.slugs import generate_slug

logger = logging.getLogger(__name__)

ATTEMPTS = 16


class ShareRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def slug_for(self, response_id: UUID) -> str | None:
        return await self.session.scalar(select(Share.slug).where(Share.response_id == response_id))

    async def get_or_create(self, response_id: UUID) -> str | None:
        existing = await self.slug_for(response_id)
        if existing is not None:
            return existing
        for _ in range(ATTEMPTS):
            share = Share(response_id=response_id, slug=generate_slug())
            self.session.add(share)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                taken = await self.slug_for(response_id)
                if taken is not None:
                    return taken
                continue
            logger.info("response=%s shared as %s", response_id, share.slug)
            return share.slug
        return None

    async def content(self, slug: str) -> str | None:
        return await self.session.scalar(
            select(Response.content)
            .join(Share, Share.response_id == Response.id)
            .where(Share.slug == slug)
            .limit(1)
        )

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[Share], int]:
        total = await self.session.scalar(select(func.count()).select_from(Share)) or 0
        rows = await self.session.scalars(
            select(Share).order_by(Share.id.desc()).offset(offset).limit(limit)
        )
        return list(rows), int(total)

    async def delete(self, slug: str) -> bool:
        row = await self.session.scalar(select(Share).where(Share.slug == slug))
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True
