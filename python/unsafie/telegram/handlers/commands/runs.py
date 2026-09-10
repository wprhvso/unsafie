from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie import artifacts
from unsafie.database import SessionLocal
from unsafie.database.repositories.turn import TurnRepository
from unsafie.settings import settings
from unsafie.telegram.sender import answer


def build_runs_router() -> Router:
    router = Router()

    @router.message(Command("runs"))
    async def runs_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        chat_id = None if (command.args or "").strip().lower() == "all" else message.chat.id
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            running = await repo.running(bot_id, chat_id)
            if not running and message.chat.type == ChatType.PRIVATE:
                running = await repo.running(bot_id)
        if not running:
            return
        links: list[str] = []
        for turn in running:
            slug = await artifacts.of_turn(turn.id)
            links.append(
                artifacts.url(slug) if slug else f"{settings.artifact_origin}/turn/{turn.id}"
            )
        await answer(message, bot_id, "\n".join(links))

    return router
