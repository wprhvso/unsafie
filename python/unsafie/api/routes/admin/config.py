from fastapi import APIRouter

from unsafie.api.schemas.models import ConfigRead, ConfigWrite
from unsafie.database import SessionLocal
from unsafie.database.repositories.config import ConfigRepository

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigRead)
async def get_config():
    async with SessionLocal() as session:
        return ConfigRead.model_validate(await ConfigRepository(session).get())


@router.put("", response_model=ConfigRead)
async def set_config(body: ConfigWrite):
    async with SessionLocal() as session:
        row = await ConfigRepository(session).set_ratios(body.ratio, body.oauth_ratio)
    return ConfigRead.model_validate(row)
