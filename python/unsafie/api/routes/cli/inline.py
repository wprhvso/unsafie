from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from unsafie.api.routes.cli.deps import Chat
from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.telegram.keyboard import parse_buttons
from unsafie.telegram.sender import _entities, chunks_of

router = APIRouter(prefix="/inline", tags=["cli"])


class EditInline(BaseModel):
    inline_message_id: str
    text: str
    buttons: str | None = None


@router.post("/messages/edit")
async def edit_inline(body: EditInline, who: Chat) -> dict:
    bot = await who.bot()
    bot_id = who.bot_id or 0
    async with SessionLocal() as session:
        turn = await session.scalar(
            select(Turn.id)
            .where(
                Turn.bot_id == bot_id,
                Turn.user_id == who.user_id,
                Turn.inline_message_id == body.inline_message_id,
            )
            .limit(1)
        )
        if turn is None:
            raise HTTPException(403, "inline message not found or does not belong to the caller")

    chunks = chunks_of(body.text)
    if len(chunks) > 1 or len(body.text) > 4096:
        raise HTTPException(400, "text exceeds Telegram inline message limit of 4096 characters")

    markup = parse_buttons(body.buttons) if body.buttons else None
    chunk = chunks[0] if chunks else {"text": body.text, "entities": []}
    try:
        await bot.edit_message_text(
            inline_message_id=body.inline_message_id,
            text=str(chunk["text"]),
            entities=_entities(chunk),
            reply_markup=markup,
        )
    except TelegramAPIError as e:
        raise HTTPException(502, f"telegram refused: {e}") from None
    return {"edited": True, "inline_message_id": body.inline_message_id}
