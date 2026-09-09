import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.database import SessionLocal
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.settings import settings
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)

EFFORT_LEVELS = ("low", "medium", "high")
DEFAULT_EFFORT = settings.gemini_thinking_level.lower()
RESET = {"default", "reset", "-"}
ALIASES = {str(i + 1): level for i, level in enumerate(EFFORT_LEVELS)}


def build_effort_router() -> Router:
    router = Router()

    @router.message(Command("effort"))
    async def effort_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        raw = (command.args or "").strip().lower()
        levels = ", ".join(EFFORT_LEVELS)
        if not raw:
            async with SessionLocal() as session:
                user = await UserRepository(session).get_or_create(user_id)
                effort = user.effort or DEFAULT_EFFORT
            await answer(
                message,
                bot_id,
                t(
                    "commands-effort-status",
                    locale,
                    effort=effort,
                    default=DEFAULT_EFFORT,
                    levels=levels,
                ),
            )
            return
        if raw in RESET:
            async with SessionLocal() as session:
                await UserRepository(session).set_effort(user_id, None)
            logger.info("bot=%s user=%s effort -> default", bot_id, user_id)
            await answer(
                message, bot_id, t("commands-effort-reset", locale, effort=DEFAULT_EFFORT)
            )
            return
        level = ALIASES.get(raw, raw)
        if level not in EFFORT_LEVELS:
            await answer(message, bot_id, t("commands-effort-usage", locale, levels=levels))
            return
        async with SessionLocal() as session:
            await UserRepository(session).set_effort(user_id, level)
        logger.info("bot=%s user=%s effort -> %s", bot_id, user_id, level)
        await answer(message, bot_id, t("commands-effort-set", locale, effort=level))

    return router
