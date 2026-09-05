import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.api.schemas.models import BotRead
from unsafie.database.models.bot import Bot
from unsafie.database.repositories.bot import BotRepository
from unsafie.database.repositories.chat import ChatRepository
from unsafie.telegram import service
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)


async def read(session: AsyncSession, bot: Bot) -> BotRead:
    _, total = await ChatRepository(session).page(limit=1, bot_id=bot.id)
    return BotRead(
        id=bot.id,
        token_masked=service.mask(bot.token),
        running=manager.is_running(bot.id),
        username=manager.username(bot.id),
        chats=total,
    )


async def listing(session: AsyncSession) -> list[BotRead]:
    return [await read(session, bot) for bot in await BotRepository(session).all()]


async def create(session: AsyncSession, token: str) -> BotRead:
    try:
        bot = await service.create(session, token)
    except service.BotTokenTaken:
        raise HTTPException(409, "a bot with this token already exists") from None
    except Exception as e:
        raise HTTPException(400, f"telegram rejected the token: {e}") from None
    return await read(session, bot)


async def update(session: AsyncSession, bot_id: int, token: str) -> BotRead:
    try:
        bot = await service.update_token(session, bot_id, token)
    except service.BotNotFound:
        raise HTTPException(404, "no such bot") from None
    except service.BotTokenTaken:
        raise HTTPException(409, "a bot with this token already exists") from None
    except Exception as e:
        raise HTTPException(400, f"telegram rejected the token: {e}") from None
    return await read(session, bot)


async def restart(session: AsyncSession, bot_id: int) -> BotRead:
    try:
        bot = await service.restart(session, bot_id)
    except service.BotNotFound:
        raise HTTPException(404, "no such bot") from None
    except Exception as e:
        raise HTTPException(400, f"could not start: {e}") from None
    return await read(session, bot)


async def delete(session: AsyncSession, bot_id: int) -> None:
    try:
        await service.delete(session, bot_id)
    except service.BotNotFound:
        raise HTTPException(404, "no such bot") from None
