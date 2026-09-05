from fastapi import APIRouter

from unsafie.api.schemas.models import BotRead, BotWrite
from unsafie.api.services import bot as service
from unsafie.database import SessionLocal

router = APIRouter(prefix="/bots", tags=["bots"])


@router.get("", response_model=list[BotRead])
async def list_bots():
    async with SessionLocal() as session:
        return await service.listing(session)


@router.post("", response_model=BotRead, status_code=201)
async def create_bot(body: BotWrite):
    async with SessionLocal() as session:
        return await service.create(session, body.token)


@router.put("/{bot_id}", response_model=BotRead)
async def update_bot(bot_id: int, body: BotWrite):
    async with SessionLocal() as session:
        return await service.update(session, bot_id, body.token)


@router.post("/{bot_id}/restart", response_model=BotRead)
async def restart_bot(bot_id: int):
    async with SessionLocal() as session:
        return await service.restart(session, bot_id)


@router.delete("/{bot_id}", status_code=204)
async def delete_bot(bot_id: int):
    async with SessionLocal() as session:
        await service.delete(session, bot_id)
