from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["telegram"])


@router.post("/api/telegram/webhook/{bot_id}")
@router.post("/tg/webhook/{bot_id}")
async def telegram_webhook(bot_id: int):
    return JSONResponse({"ok": True, "mode": "polling"})
