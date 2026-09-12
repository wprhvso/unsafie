import shutil
from pathlib import Path

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import delete, select

from unsafie.agent import queue, turns
from unsafie.database import SessionLocal
from unsafie.database.models.artifact import Artifact
from unsafie.database.models.turn import Turn
from unsafie.database.models.update import Update
from unsafie.database.repositories.turn import TurnRepository
from unsafie.fluent import t
from unsafie.log import get_logger
from unsafie.settings import settings
from unsafie.telegram.group import is_admin
from unsafie.telegram.handlers.commands.pipe import cancel_pipeline
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = get_logger(__name__)


def build_wipe_router() -> Router:
    router = Router()

    @router.message(Command("wipe", "clear"))
    async def wipe_handler(message: Message, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        chat_id = message.chat.id
        locale = await locale_for(user_id, message.from_user)

        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) and message.bot:
            admin = await is_admin(message.bot, chat_id, user_id)
            if not admin:
                await answer(message, bot_id, t("commands-group-admin-only", locale))
                return

        cancel_pipeline(bot_id, chat_id)

        async with SessionLocal() as session:
            repo = TurnRepository(session)
            running = await repo.running(bot_id, chat_id)
            for turn in running:
                await turns.stop(turn.id)
                await queue.clear(turn.id)

            turn_ids = list(await session.scalars(select(Turn.id).where(Turn.chat_id == chat_id)))

            if turn_ids:
                await session.execute(delete(Artifact).where(Artifact.turn_id.in_(turn_ids)))
            await session.execute(delete(Artifact).where(Artifact.chat_id == chat_id))
            await session.execute(delete(Update).where(Update.chat_id == chat_id))
            await session.execute(delete(Turn).where(Turn.chat_id == chat_id))
            await session.commit()

        chat_base = Path(settings.chats_dir) / str(chat_id)
        if chat_base.exists():
            shutil.rmtree(chat_base, ignore_errors=True)

        logger.info("bot=%s chat=%s user=%s wiped all chat history and artifacts", bot_id, chat_id, user_id)
        await answer(message, bot_id, t("commands-wipe-success", locale))

    return router
