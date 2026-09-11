from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie import artifacts
from unsafie.database import SessionLocal
from unsafie.database.repositories.turn import TurnRepository
from unsafie.fluent import t
from unsafie.settings import settings
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer


def build_runs_router() -> Router:
    router = Router()

    @router.message(Command("runs"))
    async def runs_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        async with SessionLocal() as session:
            repo = TurnRepository(session)
            running = await repo.running(bot_id, message.chat.id)
        if not running:
            user_id = message.from_user.id if message.from_user else 0
            locale = await locale_for(user_id, message.from_user)
            await answer(message, bot_id, t("cmd-runs-empty", locale))
            return
        links: list[str] = []
        for turn in running:
            slug = await artifacts.of_turn(turn.id)
            links.append(
                artifacts.url(slug) if slug else f"{settings.artifact_origin}/turn/{turn.id}",
            )
        await answer(message, bot_id, "\n".join(links))

    return router
