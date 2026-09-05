from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import ChatRead, MessageRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.chat import ChatRepository
from unsafie.database.repositories.history import HistoryRepository

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=Page[ChatRead])
async def list_chats(bot_id: int | None = None, params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await ChatRepository(session).page(params.offset, params.limit, bot_id)
    return Page.of([ChatRead.model_validate(r) for r in rows], total, params)


@router.get("/{bot_id}/{chat_id}", response_model=ChatRead)
async def get_chat(bot_id: int, chat_id: int):
    async with SessionLocal() as session:
        row = await ChatRepository(session).get(bot_id, chat_id)
    if row is None:
        raise HTTPException(404, "no such chat")
    return ChatRead.model_validate(row)


@router.get("/{bot_id}/{chat_id}/messages", response_model=list[MessageRead])
async def chat_messages(bot_id: int, chat_id: int, limit: int = 50, before: int | None = None):
    async with SessionLocal() as session:
        hits = await HistoryRepository(session).recent(bot_id, chat_id, min(limit, 200), before)
    return [MessageRead(**h.__dict__) for h in hits]


@router.get("/{bot_id}/{chat_id}/search", response_model=list[MessageRead])
async def chat_search(bot_id: int, chat_id: int, query: str, limit: int = 50):
    async with SessionLocal() as session:
        hits, _ = await HistoryRepository(session).search(
            bot_id, chat_id, query, limit=min(limit, 200)
        )
    return [MessageRead(**h.__dict__) for h in hits]
