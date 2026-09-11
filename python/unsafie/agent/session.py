from dataclasses import dataclass
from uuid import UUID

from aiogram import Bot

from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository


@dataclass(frozen=True)
class Ctx:
    bot: Bot
    bot_id: int
    chat_id: int
    user_id: int
    turn_id: UUID
    locale: str = "en"
    inline_message_id: str | None = None
    machine_name: str | None = None

    @property
    def prefix(self) -> str:
        return f"bot={self.bot_id} chat={self.chat_id} user={self.user_id} turn={self.turn_id}"


async def current_turn(ctx: Ctx) -> Turn | None:
    async with SessionLocal() as session:
        return await TurnRepository(session).get(ctx.turn_id)
