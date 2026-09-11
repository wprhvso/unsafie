import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.update import Update

logger = logging.getLogger(__name__)


class UpdateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_starting_offset(self, bot_id: int) -> int:
        val = await self.session.scalar(
            select(func.coalesce(func.max(Update.update_id), 0) + 1).where(Update.bot_id == bot_id)
        )
        return int(val or 1)

    async def save_batch(self, bot_id: int, items: list[dict]) -> int:
        if not items:
            return 0
        rows = []
        for item in items:
            upd_id = int(item["update_id"])
            chat_id = None
            msg_id = None
            user_id = None
            for key in ("message", "edited_message", "callback_query", "channel_post", "edited_channel_post"):
                sub = item.get(key)
                if isinstance(sub, dict):
                    if "chat" in sub and isinstance(sub["chat"], dict):
                        chat_id = sub["chat"].get("id")
                    if "message_id" in sub:
                        msg_id = sub.get("message_id")
                    if "from" in sub and isinstance(sub["from"], dict):
                        user_id = sub["from"].get("id")
                    break
            if not user_id:
                for key in ("inline_query", "chosen_inline_result"):
                    sub = item.get(key)
                    if isinstance(sub, dict) and "from" in sub and isinstance(sub["from"], dict):
                        user_id = sub["from"].get("id")
                        break
            rows.append({
                "bot_id": bot_id,
                "update_id": upd_id,
                "chat_id": chat_id,
                "message_id": msg_id,
                "user_id": user_id,
                "payload": item,
                "status": "pending",
            })
        stmt = insert(Update).values(rows).on_conflict_do_nothing(constraint="uq_updates_bot_update")
        res = await self.session.execute(stmt)
        await self.session.commit()
        return int(getattr(res, "rowcount", 0) or 0)

    async def claim_pending(self, limit: int = 50) -> list[Update]:
        query = (
            select(Update)
            .where(Update.status == "pending")
            .order_by(Update.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = await self.session.scalars(query)
        return list(rows)

    async def mark_done(self, update_db_id: int) -> None:
        await self.session.execute(
            update(Update)
            .where(Update.id == update_db_id)
            .values(status="done", processed_at=datetime.now(UTC))
        )
        await self.session.commit()

    async def mark_failed(self, update_db_id: int) -> None:
        await self.session.execute(
            update(Update)
            .where(Update.id == update_db_id)
            .values(status="failed", processed_at=datetime.now(UTC))
        )
        await self.session.commit()

    async def save(
        self,
        *,
        bot_id: int,
        update_id: int,
        chat_id: int | None,
        message_id: int | None,
        user_id: int | None,
        payload: dict,
    ) -> tuple[int, bool]:
        stmt = (
            insert(Update)
            .values(
                bot_id=bot_id,
                update_id=update_id,
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                payload=payload,
                status="pending",
            )
            .on_conflict_do_nothing(constraint="uq_updates_bot_update")
            .returning(Update.id)
        )
        stored = await self.session.scalar(stmt)
        fresh = stored is not None
        if not fresh:
            stored = await self.session.scalar(
                select(Update.id).where(Update.bot_id == bot_id, Update.update_id == update_id),
            )
            logger.info("bot=%s update=%s redelivered, row=%s", bot_id, update_id, stored)
        await self.session.commit()
        return int(stored or 0), fresh

    async def attach(self, update_db_id: int, turn_id: UUID) -> int:
        ordinal = await self.session.scalar(
            select(func.coalesce(func.max(Update.ordinal) + 1, 0)).where(Update.turn_id == turn_id),
        )
        await self.session.execute(
            update(Update).where(Update.id == update_db_id).values(turn_id=turn_id, ordinal=ordinal),
        )
        await self.session.commit()
        return int(ordinal or 0)

    async def turn_of(self, bot_id: int, chat_id: int, message_id: int) -> UUID | None:
        return await self.session.scalar(
            select(Update.turn_id)
            .where(
                Update.bot_id == bot_id,
                Update.chat_id == chat_id,
                Update.message_id == message_id,
                Update.turn_id.is_not(None),
            )
            .order_by(Update.created_at.desc(), Update.id.desc())
            .limit(1),
        )

    async def last_message_id(self, turn_id: UUID) -> int | None:
        value = await self.session.scalar(
            select(Update.message_id)
            .where(Update.turn_id == turn_id, Update.message_id.is_not(None))
            .order_by(Update.ordinal.desc())
            .limit(1),
        )
        return int(value) if value is not None else None

    async def first_for_turn(self, turn_id: UUID) -> Update | None:
        return await self.session.scalar(
            select(Update).where(Update.turn_id == turn_id).order_by(Update.ordinal.asc()).limit(1),
        )
