import asyncio
import contextlib
from unsafie.log import get_logger
from dataclasses import dataclass, field
from enum import StrEnum

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from unsafie.fluent import t

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 900.0


class LongTarget(StrEnum):
    CHAT = "chat"
    SYSTEM = "system"


class LongChoice(StrEnum):
    SEND = "send"
    RESET = "reset"


class LongCallback(CallbackData, prefix="long"):
    choice: str
    user_id: int


@dataclass
class Collected:
    target: LongTarget
    messages: list[Message]


@dataclass
class _Collection:
    user_id: int
    target: LongTarget
    locale: str
    messages: list[Message] = field(default_factory=list)
    prompt_message_id: int | None = None
    expiry: asyncio.Task[None] | None = None


def prompt_markup(locale: str, user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"✅ {t('cmd-long-send', locale)}",
            callback_data=LongCallback(choice=LongChoice.SEND.value, user_id=user_id).pack(),
        ),
        InlineKeyboardButton(
            text=f"🗑 {t('cmd-long-reset', locale)}",
            callback_data=LongCallback(choice=LongChoice.RESET.value, user_id=user_id).pack(),
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _prompt_text(target: LongTarget, locale: str, count: int = 0, chars: int = 0) -> str:
    key = "cmd-system-long-prompt" if target == LongTarget.SYSTEM else "cmd-long-prompt"
    base = t(key, locale)
    if count > 0:
        return f"{base}\n\n({count} msg, {chars} chars)"
    return base


class LongInputService:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self._collections: dict[tuple[int, int, int], _Collection] = {}

    def collecting(self, bot_id: int, chat_id: int, user_id: int) -> bool:
        return (bot_id, chat_id, user_id) in self._collections

    def target_of(self, bot_id: int, chat_id: int, user_id: int) -> LongTarget | None:
        col = self._collections.get((bot_id, chat_id, user_id))
        return col.target if col else None

    async def start(
        self,
        bot: Bot,
        bot_id: int,
        chat_id: int,
        user_id: int,
        initial_message: Message | None,
        target: LongTarget,
        locale: str,
    ) -> None:
        await self.clear(bot_id, chat_id, user_id)
        col = _Collection(user_id=user_id, target=target, locale=locale)
        if initial_message and (initial_message.text or initial_message.caption):
            col.messages.append(initial_message)

        total_chars = sum(len(m.text or m.caption or "") for m in col.messages)
        text = _prompt_text(target, locale, len(col.messages), total_chars)
        markup = prompt_markup(locale, user_id)

        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        col.prompt_message_id = sent.message_id
        col.expiry = asyncio.create_task(self._expire(bot, bot_id, chat_id, user_id, locale))
        self._collections[(bot_id, chat_id, user_id)] = col

    async def append(
        self,
        bot: Bot,
        bot_id: int,
        chat_id: int,
        user_id: int,
        message: Message,
    ) -> None:
        col = self._collections.get((bot_id, chat_id, user_id))
        if col is None:
            return

        col.messages.append(message)
        if col.expiry:
            col.expiry.cancel()
        col.expiry = asyncio.create_task(self._expire(bot, bot_id, chat_id, user_id, col.locale))

        total_chars = sum(len(m.text or m.caption or "") for m in col.messages)
        text = _prompt_text(col.target, col.locale, len(col.messages), total_chars)

        if col.prompt_message_id:
            with contextlib.suppress(Exception):
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=col.prompt_message_id,
                    text=text,
                    reply_markup=prompt_markup(col.locale, user_id),
                )

    async def close(self, bot_id: int, chat_id: int, user_id: int) -> Collected | None:
        col = self._collections.pop((bot_id, chat_id, user_id), None)
        if col is None:
            return None
        if col.expiry:
            col.expiry.cancel()
        return Collected(target=col.target, messages=col.messages)

    async def clear(self, bot_id: int, chat_id: int, user_id: int) -> None:
        col = self._collections.pop((bot_id, chat_id, user_id), None)
        if col and col.expiry:
            col.expiry.cancel()

    async def _expire(self, bot: Bot, bot_id: int, chat_id: int, user_id: int, locale: str) -> None:
        await asyncio.sleep(self.timeout)
        col = self._collections.pop((bot_id, chat_id, user_id), None)
        if col is None:
            return
        if col.prompt_message_id:
            with contextlib.suppress(Exception):
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=col.prompt_message_id,
                    text=t("cmd-long-expired", locale),
                    reply_markup=None,
                )


long_input_service = LongInputService()
