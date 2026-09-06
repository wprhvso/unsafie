import logging

from fastapi import APIRouter, Header, Request, Response

from unsafie.settings import settings
from unsafie.telegram.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tg", tags=["telegram"])


@router.post("/{secret}")
async def webhook(
    secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    if not settings.webhook_secret:
        return Response(status_code=404)
    if secret != settings.webhook_secret or x_telegram_bot_api_secret_token != settings.webhook_secret:
        return Response(status_code=404)
    data = await request.json()
    await manager.feed(data)
    return Response(status_code=200)
