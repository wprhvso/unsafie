from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import ShareRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.share import ShareRepository
from unsafie.settings import settings

router = APIRouter(prefix="/shares", tags=["shares"])


@router.get("", response_model=Page[ShareRead])
async def list_shares(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await ShareRepository(session).page(params.offset, params.limit)
    items = [ShareRead(**{**r.__dict__, "url": f"{settings.share_origin}/{r.slug}"}) for r in rows]
    return Page.of(items, total, params)


@router.delete("/{slug}", status_code=204)
async def delete_share(slug: str):
    async with SessionLocal() as session:
        if not await ShareRepository(session).delete(slug):
            raise HTTPException(404, "no such share")
