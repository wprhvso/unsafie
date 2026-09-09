import json
import os
from typing import Any

from unsafie.cli.client import client


def edit(text: str, *, inline_message_id: str | None = None, buttons: Any = None) -> dict:
    mid = inline_message_id or os.environ.get("UNSAFIE_INLINE_MESSAGE_ID")
    if not mid:
        raise ValueError("no inline_message_id available (not running in inline mode)")
    body = {
        "inline_message_id": mid,
        "text": text,
        "buttons": json.dumps(buttons, ensure_ascii=False) if buttons is not None else None,
    }
    return client().call("POST", "/inline/messages/edit", body)
