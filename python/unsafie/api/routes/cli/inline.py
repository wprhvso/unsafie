from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from unsafie.api.routes.cli.deps import Chat
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
    markup = parse_buttons(body.buttons) if body.buttons else None
    chunks = chunks_of(body.text)
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
