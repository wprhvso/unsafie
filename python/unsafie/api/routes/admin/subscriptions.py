from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import SubscriptionRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.subscription import SubscriptionRepository

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("", response_model=Page[SubscriptionRead])
async def list_subscriptions(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await SubscriptionRepository(session).page(params.offset, params.limit)
    items = [
        SubscriptionRead(
            id=s.id,
            bot_id=s.bot_id,
            chat_id=s.chat_id,
            user_id=s.user_id,
            repo=r.full,
            kind=s.kind,
            filters=s.filters or {},
            created_at=s.created_at,
        )
        for s, r in rows
    ]
    return Page.of(items, total, params)


@router.delete("/{sub_id}", status_code=204)
async def delete_subscription(sub_id: int):
    async with SessionLocal() as session:
        if not await SubscriptionRepository(session).delete(sub_id):
            raise HTTPException(404, "no such subscription")
