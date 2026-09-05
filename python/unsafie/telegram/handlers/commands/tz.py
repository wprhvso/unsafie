import logging
from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.fluent import t
from unsafie.scheduler import service
from unsafie.scheduler.when import WhenError, fmt_local, zone
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


def build_tz_router() -> Router:
    router = Router()

    @router.message(Command("tz", "timezone"))
    async def tz_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        raw = (command.args or "").strip()
        if not raw:
            name = await service.timezone_of(user_id)
            now = fmt_local(datetime.now(UTC), zone(name))
            await answer(message, bot_id, t("tz-current", locale, name=name, now=now))
            return
        try:
            name = await service.set_timezone(user_id, raw)
        except WhenError as e:
            await answer(message, bot_id, str(e))
            return
        now = fmt_local(datetime.now(UTC), zone(name))
        await answer(message, bot_id, t("tz-set", locale, name=name, now=now))

    return router
