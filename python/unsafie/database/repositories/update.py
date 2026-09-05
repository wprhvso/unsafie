import logging
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.update import Update

logger = logging.getLogger(__name__)


class UpdateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(
        self,
        *,
        bot_id: int,
        update_id: int,
        chat_id: int | None,
        message_id: int | None,
        user_id: int | None,
        payload: dict,
    ) -> int:
        stmt = (
            insert(Update)
            .values(
                bot_id=bot_id,
                update_id=update_id,
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                payload=payload,
            )
            .on_conflict_do_nothing(constraint="uq_updates_bot_update")
            .returning(Update.id)
        )
        stored = await self.session.scalar(stmt)
        if stored is None:
            stored = await self.session.scalar(
                select(Update.id).where(Update.bot_id == bot_id, Update.update_id == update_id)
            )
            logger.info("bot=%s update=%s redelivered, row=%s", bot_id, update_id, stored)
        await self.session.commit()
        return int(stored)

    async def attach(self, update_db_id: int, turn_id: UUID) -> int:
        ordinal = await self.session.scalar(
            select(func.coalesce(func.max(Update.ordinal) + 1, 0)).where(Update.turn_id == turn_id)
        )
        await self.session.execute(
            update(Update).where(Update.id == update_db_id).values(turn_id=turn_id, ordinal=ordinal)
        )
        await self.session.commit()
        return int(ordinal)

    async def last_message_id(self, turn_id: UUID) -> int | None:
        value = await self.session.scalar(
            select(Update.message_id)
            .where(Update.turn_id == turn_id, Update.message_id.is_not(None))
            .order_by(Update.ordinal.desc())
            .limit(1)
        )
        return int(value) if value is not None else None
