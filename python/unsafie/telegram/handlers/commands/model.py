import logging
import re

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

MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RESET = {"default", "reset", "-"}


def build_model_router() -> Router:
    router = Router()

    @router.message(Command("model"))
    async def model_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        raw = (command.args or "").strip()
        async with SessionLocal() as session:
            users = UserRepository(session)
            if not raw:
                user = await users.get_or_create(user_id)
                await answer(
                    message,
                    bot_id,
                    t(
                        "commands-model-status",
                        locale,
                        model=user.model or settings.claude_model,
                        default=settings.claude_model,
                    ),
                )
                return
            if raw.lower() in RESET:
                await users.set_model(user_id, None)
                logger.info("bot=%s user=%s model -> default", bot_id, user_id)
                await answer(
                    message, bot_id, t("commands-model-reset", locale, model=settings.claude_model)
                )
                return
            if not MODEL_RE.match(raw):
                await answer(message, bot_id, t("commands-model-usage", locale))
                return
            await users.set_model(user_id, raw)
        logger.info("bot=%s user=%s model -> %s", bot_id, user_id, raw)
        await answer(message, bot_id, t("commands-model-set", locale, model=raw))

    return router
