import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from unsafie.telegram import bots
from unsafie.telegram.webhook import dispatcher, mark_active, secret_token_for

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


@router.post("/api/telegram/webhook/{bot_id}")
@router.post("/tg/webhook/{bot_id}")
async def telegram_webhook(
    bot_id: int,
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
):
    bot = await bots.bot_for(bot_id)
    if bot is None:
        logger.warning("telegram webhook: unknown bot_id=%s", bot_id)
        return Response(status_code=404)
    expected = secret_token_for(bot.token)
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, expected
    ):
        logger.warning("telegram webhook bot_id=%s: bad secret token", bot_id)
        return Response(status_code=401)
    try:
        payload = await request.json()
    except Exception:
        logger.warning("telegram webhook bot_id=%s: invalid json body", bot_id)
        return Response(status_code=400)
    await mark_active(bot_id)
    try:
        await dispatcher.feed_raw_update(bot, payload, bot_id=bot_id)
    except Exception:
        logger.exception("telegram webhook bot_id=%s: update processing failed", bot_id)
    return JSONResponse({"ok": True})
