import json

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_LIMIT = 64
MAX_BUTTONS = 100
MAX_PER_ROW = 8


class ButtonsError(ValueError):
    pass


def _button(item) -> InlineKeyboardButton:
    if isinstance(item, str):
        item = {"text": item, "data": item}
    if not isinstance(item, dict) or not str(item.get("text") or "").strip():
        msg = f"a button is a string or an object with text: {item!r}"
        raise ButtonsError(msg)
    text = str(item["text"]).strip()
    url = item.get("url")
    if url:
        return InlineKeyboardButton(text=text, url=str(url))
    data = item.get("data", item.get("callback_data"))
    data = text if data is None else str(data)
    if len(data.encode()) > CALLBACK_LIMIT:
        msg = f"button data for {text!r} exceeds {CALLBACK_LIMIT} bytes: {data!r}"
        raise ButtonsError(msg)
    return InlineKeyboardButton(text=text, callback_data=data)


def parse_buttons(raw: str | None) -> InlineKeyboardMarkup | None:
    if raw is None or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        msg = f"buttons is not JSON: {e}"
        raise ButtonsError(msg) from e
    if isinstance(data, str | dict):
        data = [data]
    if not isinstance(data, list):
        msg = "buttons must be a JSON list of rows"
        raise ButtonsError(msg)
    rows: list[list[InlineKeyboardButton]] = []
    for row in data:
        items = row if isinstance(row, list) else [row]
        if not items:
            continue
        if len(items) > MAX_PER_ROW:
            msg = f"more than {MAX_PER_ROW} buttons in a row"
            raise ButtonsError(msg)
        rows.append([_button(i) for i in items])
    if sum(len(r) for r in rows) > MAX_BUTTONS:
        msg = f"more than {MAX_BUTTONS} buttons"
        raise ButtonsError(msg)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def describe(markup: InlineKeyboardMarkup | None) -> str:
    if markup is None or not markup.inline_keyboard:
        return ""
    return " | ".join(" ".join(f"[{b.text}]" for b in row) for row in markup.inline_keyboard)
