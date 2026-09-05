from fastapi import APIRouter

from yet_another_claude_bot.api.dependencies.database import Session
from yet_another_claude_bot.api.schemas.config import RatioRead, RatioUpdate
from yet_another_claude_bot.repositories.config import ConfigRepository

router = APIRouter(prefix="/ratio", tags=["config"])


@router.get("", response_model=RatioRead)
async def get_ratio(session: Session) -> RatioRead:
    return await ConfigRepository(session).get()


@router.put("", response_model=RatioRead)
async def set_ratio(payload: RatioUpdate, session: Session) -> RatioRead:
    return await ConfigRepository(session).set_ratios(payload.ratio, payload.oauth_ratio)
