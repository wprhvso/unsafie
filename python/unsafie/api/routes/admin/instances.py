from fastapi import APIRouter

from unsafie.presence import instances

router = APIRouter(prefix="/instances", tags=["instances"])


@router.get("")
async def list_instances():
    return {"items": await instances()}
