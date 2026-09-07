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
    return _prune(model.model_dump(mode="json", exclude_none=True, fallback=_fallback))
