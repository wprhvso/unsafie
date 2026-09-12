from unsafie.log import get_logger

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.api.schemas.models import BotRead
from unsafie.database.models.bot import Bot
from unsafie.database.repositories.bot import BotRepository
from unsafie.database.repositories.chat import ChatRepository
from unsafie.telegram import service, webhook

logger = get_logger(__name__)


async def read(
    session: AsyncSession, bot: Bot, polled: dict[int, str | None] | None = None,
) -> BotRead:
    _, total = await ChatRepository(session).page(limit=1, bot_id=bot.id)
    if polled is None:
        polled = await webhook.polled_by([bot.id])
    owner = polled.get(bot.id)
    return BotRead(
        id=bot.id,
        token_masked=service.mask(bot.token),
        running=owner is not None,
        polled_by=owner,
        username=bot.username or None,
        chats=total,
    )


async def listing(session: AsyncSession) -> list[BotRead]:
    rows = await BotRepository(session).all()
    polled = await webhook.polled_by([row.id for row in rows])
    return [await read(session, row, polled) for row in rows]


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
