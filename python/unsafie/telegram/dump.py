"""JSON-safe dump of aiogram objects.

Telegram omits the optional fields of nested objects — a message with a link
arrives with ``link_preview_options={"url": ...}`` — and aiogram fills the rest
with ``Default`` sentinels meant for outgoing requests. Pydantic cannot put such
an object into JSON and raises ``PydanticSerializationError: Unable to serialize
unknown type: <class 'aiogram.client.default.Default'>``, so the sentinels are
turned into ``None`` and dropped along with the other empty fields.
"""

from typing import Any

from aiogram.client.default import Default
from pydantic import BaseModel


def _fallback(value: Any) -> Any:
    if isinstance(value, Default):
        return None
    return str(value)


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _prune(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_prune(item) for item in value]
    return value


def dump(model: BaseModel) -> Any:
    """Model as JSON-ready data: no sentinels, no empty fields."""
    return _prune(model.model_dump(mode="json", exclude_none=True, fallback=_fallback))
