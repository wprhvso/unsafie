import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.database import SessionLocal
from unsafie.database.repositories.schedule import ScheduleRepository
from unsafie.database.repositories.watch import WatchRepository
from unsafie.fluent import t
from unsafie.scheduler import service
from unsafie.ssh import watches
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


def build_tasks_router() -> Router:
    router = Router()

    @router.message(Command("tasks"))
    async def tasks_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        chat_id = message.chat.id
        arg = (command.args or "").strip().lower()
        async with SessionLocal() as session:
            schedule = ScheduleRepository(session)
            watchdog = WatchRepository(session)
            if arg in ("clear", "rm all"):
                n = await schedule.remove_all(bot_id, chat_id)
                m = await watchdog.remove_all(bot_id, chat_id)
                await answer(message, bot_id, t("tasks-cleared", locale, tasks=n, watches=m))
                return
            tasks = await schedule.for_chat(bot_id, chat_id)
            checks = await watchdog.for_chat(bot_id, chat_id)
        blocks = [service.summary(tasks, locale)]
        if checks:
            blocks.append(t("tasks-watches", locale))
            blocks += [watches.describe(w, h, locale) for w, h in checks]
        blocks.append(t("tasks-hint", locale))
        await answer(message, bot_id, "\n".join(blocks))

    return router
