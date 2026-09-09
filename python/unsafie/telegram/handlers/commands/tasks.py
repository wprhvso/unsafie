from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.schedule import ScheduleRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.database.repositories.watch import WatchRepository
from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer


async def _turn_text(session: AsyncSession, turn: Turn) -> str:
    if turn.title:
        return turn.title
    update = await UpdateRepository(session).first_for_turn(turn.id)
    if update and update.payload:
        msg = update.payload.get("message") or update.payload.get("channel_post") or {}
        raw = msg.get("text") or msg.get("caption") or ""
        if raw:
            line = raw.strip().splitlines()[0].strip()
            if line:
                return line
    return str(turn.id)


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
            if arg in ("clear", "rm all"):
                watchdog = WatchRepository(session)
                n = await schedule.remove_all(bot_id, chat_id)
                m = await watchdog.remove_all(bot_id, chat_id)
                await answer(message, bot_id, t("tasks-cleared", locale, tasks=n, watches=m))
                return
            turns = await TurnRepository(session).running(bot_id, chat_id)
            scheduled = await schedule.for_chat(bot_id, chat_id)
            items: list[tuple[datetime, str]] = []
            for turn in turns:
                text = await _turn_text(session, turn)
                items.append((turn.created_at, text))
            for task in scheduled:
                text = task.text.strip() if task.text else str(task.id)
                items.append((task.created_at, text))
        if not items:
            await answer(message, bot_id, t("tasks-empty", locale))
            return
        items.sort(key=lambda item: item[0])
        await answer(message, bot_id, "\n".join(text for _, text in items))

    return router
