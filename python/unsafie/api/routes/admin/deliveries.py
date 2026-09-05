from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Ok, Page, PageParams
from unsafie.api.schemas.models import DeliveryDetail, DeliveryRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.delivery import DeliveryRepository
from unsafie.settings import settings

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.get("", response_model=Page[DeliveryRead])
async def list_deliveries(
    event: str | None = None, errors_only: bool = False, params: PageParams = Depends(paging)
):
    async with SessionLocal() as session:
        rows, total = await DeliveryRepository(session).page(
            params.offset, params.limit, event, errors_only
        )
    return Page.of([DeliveryRead.model_validate(r) for r in rows], total, params)


@router.get("/{delivery_id}", response_model=DeliveryDetail)
async def get_delivery(delivery_id: str):
    async with SessionLocal() as session:
        row = await DeliveryRepository(session).get(delivery_id)
    if row is None:
        raise HTTPException(404, "no such delivery")
    return DeliveryDetail.model_validate(row)


@router.post("/purge", response_model=Ok)
async def purge(keep_days: int | None = None):
    async with SessionLocal() as session:
        removed = await DeliveryRepository(session).purge(keep_days or settings.webhook_keep_days)
    return Ok(detail=f"{removed} delivery(ies) removed")
