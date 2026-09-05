from aiogram.exceptions import TelegramUnauthorizedError
from fastapi import APIRouter, HTTPException, status

from yet_another_claude_bot.api.dependencies.bot import BotServiceDep
from yet_another_claude_bot.api.schemas.bot import BotCreate, BotRead, BotUpdate
from yet_another_claude_bot.api.services.bot import BotNotFound, BotTokenTaken

router = APIRouter(prefix="/bots", tags=["bots"])


@router.get("", response_model=list[BotRead])
async def list_bots(service: BotServiceDep) -> list[BotRead]:
    return await service.list()


@router.get("/{bot_id}", response_model=BotRead)
async def get_bot(bot_id: int, service: BotServiceDep) -> BotRead:
    try:
        return await service.get(bot_id)
    except BotNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.post("", response_model=BotRead, status_code=status.HTTP_201_CREATED)
async def create_bot(payload: BotCreate, service: BotServiceDep) -> BotRead:
    try:
        return await service.create(payload.token)
    except BotTokenTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "token already exists")
    except TelegramUnauthorizedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid token")


@router.put("/{bot_id}", response_model=BotRead)
async def update_bot(
    bot_id: int, payload: BotUpdate, service: BotServiceDep
) -> BotRead:
    try:
        return await service.update(bot_id, payload.token)
    except BotNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    except BotTokenTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "token already exists")
    except TelegramUnauthorizedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid token")


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(bot_id: int, service: BotServiceDep) -> None:
    try:
        await service.delete(bot_id)
    except BotNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
