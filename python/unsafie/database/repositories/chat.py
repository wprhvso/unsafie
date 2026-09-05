from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.chat import Chat


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def touch(
        self, bot_id: int, chat_id: int, type_: str, title: str | None, username: str | None
    ) -> None:
        now = datetime.now(UTC)
        stmt = insert(Chat).values(
            bot_id=bot_id,
            chat_id=chat_id,
            type=type_,
            title=title,
            username=username,
            first_seen=now,
            last_seen=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_chats_bot_chat",
            set_={"type": type_, "title": title, "username": username, "last_seen": now},
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get(self, bot_id: int, chat_id: int) -> Chat | None:
        return await self.session.scalar(
            select(Chat).where(Chat.bot_id == bot_id, Chat.chat_id == chat_id)
        )

    async def page(
        self, offset: int = 0, limit: int = 50, bot_id: int | None = None
    ) -> tuple[list[Chat], int]:
        cond = [Chat.bot_id == bot_id] if bot_id is not None else []
        total = await self.session.scalar(select(func.count()).select_from(Chat).where(*cond)) or 0
        rows = await self.session.scalars(
            select(Chat).where(*cond).order_by(Chat.last_seen.desc()).offset(offset).limit(limit)
        )
        return list(rows), int(total)
