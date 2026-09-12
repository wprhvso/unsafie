from unsafie.log import get_logger
from typing import Final

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from unsafie.database import SessionLocal
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.settings import settings
from unsafie.telegram.handlers.locale import KNOWN, guess
from unsafie.telegram.sender import answer

logger = get_logger(__name__)

LANGUAGES: Final = ("en", "ru", "es", "fr", "ar", "fa")
RESET: Final = {"default", "reset", "auto", "-"}

LANGUAGE_NAMES: Final = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "es": "🇪🇸 Español",
    "fr": "🇫🇷 Français",
    "ar": "🇸🇦 العربية",
    "fa": "🇮🇷 فارسی",
}

ALIASES: Final = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "русский": "ru",
    "рус": "ru",
    "es": "es",
    "esp": "es",
    "spa": "es",
    "spanish": "es",
    "español": "es",
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "french": "fr",
    "français": "fr",
    "ar": "ar",
    "ara": "ar",
    "arabic": "ar",
    "العربية": "ar",
    "عربي": "ar",
    "fa": "fa",
    "fas": "fa",
    "per": "fa",
    "persian": "fa",
    "farsi": "fa",
    "فارسی": "fa",
}


class LangCallback(CallbackData, prefix="lang"):
    code: str


def lang_keyboard(current_code: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for code in LANGUAGES:
        name = LANGUAGE_NAMES.get(code, code)
        marker = "🔘" if code == current_code else "⚪"
        btn = InlineKeyboardButton(
            text=f"{marker} {name}", callback_data=LangCallback(code=code).pack(),
        )
        pair.append(btn)
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    auto_marker = "🔘" if current_code is None else "⚪"
    rows.append(
        [
            InlineKeyboardButton(
                text=f"{auto_marker} 🌐 Auto (Telegram)",
                callback_data=LangCallback(code="default").pack(),
            ),
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_lang(raw: str) -> str | None:
    code = raw.strip().lower()
    return ALIASES.get(code)


def build_lang_router() -> Router:
    router = Router()

    @router.message(Command("lang", "language"))
    async def lang_command(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        raw = (command.args or "").strip().lower()
        supported = ", ".join(LANGUAGES)

        async with SessionLocal() as session:
            user = await UserRepository(session).get_or_create(user_id)
            current_locale = user.locale

        if not raw:
            effective = current_locale or guess(message.from_user)
            markup = lang_keyboard(current_locale)
            await answer(
                message,
                bot_id,
                t(
                    "commands-lang-status",
                    effective,
                    current=LANGUAGE_NAMES.get(effective, effective),
                    languages=supported,
                ),
                reply_markup=markup,
            )
            return

        if raw in RESET:
            async with SessionLocal() as session:
                await UserRepository(session).set_locale(user_id, None)
            new_locale = guess(message.from_user)
            logger.info("bot=%s user=%s lang -> auto (%s)", bot_id, user_id, new_locale)
            await answer(
                message,
                bot_id,
                t(
                    "commands-lang-reset",
                    new_locale,
                    language=LANGUAGE_NAMES.get(new_locale, new_locale),
                ),
            )
            return

        chosen = parse_lang(raw)
        if chosen is None or chosen not in KNOWN:
            await answer(
                message,
                bot_id,
                t(
                    "commands-lang-usage",
                    current_locale or settings.default_locale,
                    languages=supported,
                ),
            )
            return

        async with SessionLocal() as session:
            await UserRepository(session).set_locale(user_id, chosen)
        logger.info("bot=%s user=%s lang -> %s", bot_id, user_id, chosen)
        await answer(
            message,
            bot_id,
            t("commands-lang-set", chosen, language=LANGUAGE_NAMES.get(chosen, chosen)),
        )

    @router.callback_query(LangCallback.filter())
    async def lang_callback(query: CallbackQuery, callback_data: LangCallback, bot_id: int) -> None:
        if not query.message or not query.bot:
            await query.answer()
            return

        user_id = query.from_user.id
        code = callback_data.code

        async with SessionLocal() as session:
            users = UserRepository(session)
            if code == "default":
                await users.set_locale(user_id, None)
                new_locale = guess(query.from_user)
                selected = None
            else:
                new_locale = code
                selected = code
                await users.set_locale(user_id, code)

        lang_name = LANGUAGE_NAMES.get(new_locale, new_locale)
        await query.answer(t("commands-lang-set", new_locale, language=lang_name))

        try:
            new_markup = lang_keyboard(selected)
            await query.bot.edit_message_reply_markup(
                chat_id=query.message.chat.id,
                message_id=query.message.message_id,
                reply_markup=new_markup,
            )
        except Exception:
            pass

    return router
