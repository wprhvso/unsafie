import hashlib
from enum import StrEnum

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InlineQueryResultUnion,
    InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from unsafie.fluent import t


class InlineVariant(StrEnum):
    TEXT = "text"
    PAGE = "page"


def answer_markup(locale: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("inline-again", locale),
        switch_inline_query_current_chat="",
    )
    return builder.as_markup()


def prompt_button(locale: str) -> InlineQueryResultsButton:
    return InlineQueryResultsButton(
        text=t("inline-prompt", locale),
        start_parameter="inline",
    )


def result_id(variant: InlineVariant, question: str) -> str:
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]
    return f"{variant.value}:{digest}"


def pending_content(question: str, locale: str) -> str:
    header = question[:256]
    pending = t("inline-pending", locale)
    return f"> {header}\n\n{pending}"


def make_results(question: str, locale: str) -> list[InlineQueryResultUnion]:
    content = pending_content(question, locale)
    markup = answer_markup(locale)
    items: list[InlineQueryResultUnion] = []
    for variant in InlineVariant:
        title = t(f"inline-{variant.value}-title", locale)
        description = t(f"inline-{variant.value}-hint", locale)
        items.append(
            InlineQueryResultArticle(
                id=result_id(variant, question),
                title=title,
                description=description,
                reply_markup=markup,
                input_message_content=InputTextMessageContent(
                    message_text=content,
                ),
            )
        )
    return items
