import logging

from aiogram.types import Update

from unsafie.database import SessionLocal
from unsafie.database.models.job import JobKind
from unsafie.database.repositories.job import JobRepository
from unsafie.settings import settings

logger = logging.getLogger(__name__)


def lane_for(user_id: int) -> str:
    return settings.default_lane


def _target(update: Update) -> tuple[int | None, int | None]:
    if update.message is not None:
        m = update.message
        return m.chat.id, (m.from_user.id if m.from_user else None)
    if update.callback_query is not None:
        q = update.callback_query
        chat = q.message.chat.id if q.message else None
        return chat, q.from_user.id
    return None, None


async def enqueue_update(bot_id: int, update: Update) -> int | None:
    chat_id, user_id = _target(update)
    if chat_id is None or user_id is None:
        return None
    async with SessionLocal() as session:
        return await JobRepository(session).enqueue(
            kind=JobKind.UPDATE,
            bot_id=bot_id,
            chat_id=chat_id,
            user_id=user_id,
            lane=lane_for(user_id),
            payload=update.model_dump(mode="json", exclude_none=True),
            update_id=update.update_id,
        )
