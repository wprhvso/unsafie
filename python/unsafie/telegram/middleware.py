import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat, Update

from unsafie import events, telemetry
from unsafie.database import SessionLocal
from unsafie.database.repositories.chat import ChatRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.log import short
from unsafie.telegram.dump import dump
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

UPDATE_DB_ID_KEY = "update_db_id"


def _preview(text: str | None, limit: int = 120) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


class UpdateMiddleware(BaseMiddleware):
    def __init__(self, bot_id: int) -> None:
        self.bot_id = bot_id

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        # The root of everything that follows: storing the update, routing it into a turn, the
        # agent run and every message it sends back all hang off this span.
        with telemetry.span(
            "tg.update",
            kind=telemetry.CONSUMER,
            attributes={
                "messaging.system": "telegram",
                "messaging.operation.name": "process",
                attrs.BOT_ID: self.bot_id,
                attrs.UPDATE_ID: event.update_id,
                attrs.TG_UPDATE_TYPE: event.event_type,
            },
        ):
            logger.info(
                "bot=%s update=%s type=%s received", self.bot_id, event.update_id, event.event_type
            )
            payload = dump(event)
            logger.debug(
                "bot=%s update=%s payload=%s", self.bot_id, event.update_id, short(payload)
            )
            data[UPDATE_DB_ID_KEY] = await self._store(event, payload)
            try:
                return await handler(event, data)
            except Exception:
                logger.exception(
                    "bot=%s update=%s failed after %.1fms",
                    self.bot_id,
                    event.update_id,
                    (time.perf_counter() - started) * 1000,
                )
                raise
            finally:
                logger.info(
                    "bot=%s update=%s handled in %.1fms",
                    self.bot_id,
                    event.update_id,
                    (time.perf_counter() - started) * 1000,
                )

    async def _store(self, event: Update, payload: Any) -> int | None:
        chat: Chat | None = None
        message_id: int | None = None
        user_id: int | None = None
        if event.message is not None:
            chat = event.message.chat
            message_id = event.message.message_id
            user_id = event.message.from_user.id if event.message.from_user else None
        elif event.edited_message is not None:
            chat = event.edited_message.chat
            user_id = event.edited_message.from_user.id if event.edited_message.from_user else None
        elif event.message_reaction is not None:
            chat = event.message_reaction.chat
            user_id = event.message_reaction.user.id if event.message_reaction.user else None
        elif event.callback_query is not None:
            message = event.callback_query.message
            chat = message.chat if message is not None else None
            user_id = event.callback_query.from_user.id
        telemetry.annotate(
            **{
                attrs.CHAT_ID: chat.id if chat else None,
                attrs.USER_ID: user_id,
                attrs.MESSAGE_ID: message_id,
                attrs.PROMPT: telemetry.content(payload),
            }
        )
        try:
            async with SessionLocal() as session:
                if chat is not None:
                    await ChatRepository(session).touch(
                        self.bot_id, chat.id, chat.type, chat.title or chat.full_name, chat.username
                    )
                stored = await UpdateRepository(session).save(
                    bot_id=self.bot_id,
                    update_id=event.update_id,
                    chat_id=chat.id if chat else None,
                    message_id=message_id,
                    user_id=user_id,
                    payload=payload,
                )
        except Exception:
            logger.exception("bot=%s update=%s not persisted", self.bot_id, event.update_id)
            return None
        if event.message is not None and chat is not None:
            events.publish(
                "message.in",
                bot_id=self.bot_id,
                chat_id=chat.id,
                message_id=message_id,
                user_id=user_id,
                text=_preview(event.message.text or event.message.caption),
            )
        return stored
