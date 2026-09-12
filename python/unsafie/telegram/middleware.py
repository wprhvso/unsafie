import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject, Update

from unsafie import events, telemetry
from unsafie.database import SessionLocal
from unsafie.database.repositories.chat import ChatRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.log import bind_contextvars, clear_contextvars, get_logger, short
from unsafie.telegram.dump import dump
from unsafie.telemetry import attrs

logger = get_logger(__name__)

UPDATE_DB_ID_KEY = "update_db_id"


def _preview(text: str | None, limit: int = 120) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


class UpdateMiddleware(BaseMiddleware):
    def __init__(self, bot_id: int | None = None) -> None:
        self.bot_id = bot_id

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        bot_id = self.bot_id if self.bot_id is not None else data.get("bot_id", 0)
        data["bot_id"] = bot_id
        started = time.perf_counter()
        clear_contextvars()
        chat, message_id, user_id = self._extract_info(event)
        bind_contextvars(
            bot_id=bot_id,
            update_id=event.update_id,
            update_type=event.event_type,
            chat_id=chat.id if chat else None,
            user_id=user_id,
            message_id=message_id,
        )
        with telemetry.span(
            "tg.update",
            kind=telemetry.CONSUMER,
            attributes={
                "messaging.system": "telegram",
                "messaging.operation.name": "process",
                attrs.BOT_ID: bot_id,
                attrs.UPDATE_ID: event.update_id,
                attrs.TG_UPDATE_TYPE: event.event_type,
            },
        ):
            logger.info(
                "telegram.update.received",
                bot_id=bot_id,
                update_id=event.update_id,
                update_type=event.event_type,
            )
            payload = dump(event)
            logger.debug(
                "telegram.update.payload",
                bot_id=bot_id,
                update_id=event.update_id,
                payload=short(payload),
            )
            telemetry.annotate(
                **{
                    attrs.CHAT_ID: chat.id if chat else None,
                    attrs.USER_ID: user_id,
                    attrs.MESSAGE_ID: message_id,
                    attrs.PROMPT: telemetry.content(payload),
                },
            )
            if chat is not None:
                try:
                    async with SessionLocal() as session:
                        await ChatRepository(session).touch(
                            bot_id,
                            chat.id,
                            chat.type,
                            chat.title or chat.full_name,
                            chat.username,
                        )
                except Exception:
                    logger.warning(
                        "telegram.chat.touch_failed",
                        bot_id=bot_id,
                        chat_id=chat.id,
                        exc_info=True,
                    )

            if UPDATE_DB_ID_KEY not in data:
                try:
                    async with SessionLocal() as session:
                        stored, fresh = await UpdateRepository(session).save(
                            bot_id=bot_id,
                            update_id=event.update_id,
                            chat_id=chat.id if chat else None,
                            message_id=message_id,
                            user_id=user_id,
                            payload=payload,
                        )
                    if not fresh:
                        telemetry.annotate(**{attrs.DUPLICATE: True})
                        logger.warning(
                            "telegram.update.duplicate",
                            bot_id=bot_id,
                            update_id=event.update_id,
                        )
                        return None
                    data[UPDATE_DB_ID_KEY] = stored
                except Exception:
                    logger.exception(
                        "telegram.update.storage_failed",
                        bot_id=bot_id,
                        update_id=event.update_id,
                    )

            if event.message is not None and chat is not None:
                events.publish(
                    "message.in",
                    bot_id=bot_id,
                    chat_id=chat.id,
                    message_id=message_id,
                    user_id=user_id,
                    text=_preview(event.message.text or event.message.caption),
                )
            try:
                res = await handler(event, data)
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.info(
                    "telegram.update.handled",
                    bot_id=bot_id,
                    update_id=event.update_id,
                    duration_ms=duration_ms,
                )
                return res
            except Exception:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.exception(
                    "telegram.update.failed",
                    bot_id=bot_id,
                    update_id=event.update_id,
                    duration_ms=duration_ms,
                )
                raise

    def _extract_info(self, event: Update) -> tuple[Chat | None, int | None, int | None]:
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
        elif event.chosen_inline_result is not None:
            user_id = event.chosen_inline_result.from_user.id if event.chosen_inline_result.from_user else None
        elif event.inline_query is not None:
            user_id = event.inline_query.from_user.id if event.inline_query.from_user else None
        return chat, message_id, user_id
