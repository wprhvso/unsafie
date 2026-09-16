from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from unsafie.aistudio.browser import RateLimitError
from unsafie.aistudio.client import get_default_client
from unsafie.aistudio.formatter import format_chat_prompt
from unsafie.log import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        kind: str,
        message: str,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{status} {kind}: {message}")
        self.status = status
        self.kind = kind
        self.message = message
        self.request_id = request_id
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status in (408, 409, 425, 429, 500, 502, 503, 504) or self.kind in (
            "RESOURCE_EXHAUSTED",
            "UNAVAILABLE",
            "DEADLINE_EXCEEDED",
            "INTERNAL",
            "ABORTED",
        )

    def describe(self) -> str:
        tail = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.status} {self.kind}: {self.message}{tail}"


@dataclass
class Reply:
    id: str = ""
    model: str = ""
    text: str = ""
    thoughts: str = ""
    thought_signatures: list[str] = field(default_factory=list)
    raw_parts: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    raw: list[dict] = field(default_factory=list)
    credential_id: int | None = None
    access_token: str | None = None

    @property
    def content(self) -> list[dict]:
        return self.raw_parts or ([{"type": "text", "text": self.text}] if self.text else [])

    @property
    def calls(self) -> list[dict]:
        return []

    def as_message(self) -> dict:
        return {"role": "assistant", "content": self.raw_parts or self.text}

    def dump(self) -> dict:
        data = {
            "model": self.model,
            "text": self.text,
            "thoughts": self.thoughts,
            "thought_signatures": self.thought_signatures,
            "raw_parts": self.raw_parts,
            "stop_reason": self.stop_reason,
            "usage": self.usage,
            "raw": self.raw,
        }
        if self.id:
            data["id"] = self.id
        return data


def _merge_parts(parts: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for part in parts:
        if not merged:
            merged.append(dict(part))
            continue
        last = merged[-1]
        can_merge_text = (
            "text" in part
            and "text" in last
            and part.get("thought") == last.get("thought")
            and "thoughtSignature" not in part
            and "thoughtSignature" not in last
            and "signature" not in part
            and "signature" not in last
        )
        if can_merge_text:
            last["text"] = str(last.get("text", "")) + str(part.get("text", ""))
        else:
            merged.append(dict(part))
    return merged


def _continuation_body(original_body: dict, reply: Reply) -> dict:
    new_body = copy.deepcopy(original_body)
    contents = new_body.get("contents")
    if not isinstance(contents, list):
        contents = []
        new_body["contents"] = contents

    parts = _merge_parts(reply.raw_parts)
    if not parts and reply.text:
        parts = [{"text": reply.text}]

    if contents and contents[-1].get("role") in ("model", "assistant"):
        existing_parts = contents[-1].get("parts") or []
        contents[-1]["parts"] = _merge_parts(existing_parts + parts)
    else:
        contents.append({"role": "model", "parts": parts})

    return new_body


async def close_session() -> None:
    pass


async def session() -> Any:
    return None


async def send(
    access_token: str,
    model: str,
    body: dict,
    *,
    credential_id: int | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> Reply:
    formatted_prompt = format_chat_prompt(body)
    if on_event:
        on_event("message_start", {"model": model})

    ai_client = get_default_client()
    try:
        response_text = await ai_client.generate(formatted_prompt)
        raw_text = str(response_text)
    except RateLimitError as e:
        raise ApiError(429, "RESOURCE_EXHAUSTED", str(e)) from e
    except Exception as e:
        raise ApiError(500, "INTERNAL", str(e)) from e

    if on_event:
        on_event("text_delta", {"text": raw_text})

    usage = {
        "input_tokens": max(1, len(formatted_prompt) // 4),
        "output_tokens": max(1, len(raw_text) // 4),
        "total_tokens": max(2, (len(formatted_prompt) + len(raw_text)) // 4),
    }
    if on_event:
        on_event("message_delta", {"usage": usage, "stop_reason": "STOP"})

    return Reply(
        id=uuid.uuid4().hex,
        model=model,
        text=raw_text,
        stop_reason="STOP",
        usage=usage,
        raw_parts=[{"text": raw_text}],
        credential_id=credential_id,
        access_token=access_token,
    )
