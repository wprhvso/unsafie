import logging
from typing import Any

from unsafie.settings import settings

logger = logging.getLogger(__name__)

SAFETY_CATEGORIES = (
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
)


def safety_settings() -> list[dict[str, str]]:
    threshold = settings.gemini_safety_threshold
    return [{"category": category, "threshold": threshold} for category in SAFETY_CATEGORIES]


def generation_config(effort: str | None, max_tokens: int) -> dict[str, Any]:
    level = (effort or settings.gemini_thinking_level).lower()
    return {
        "maxOutputTokens": max_tokens,
        "thinkingConfig": {
            "thinkingLevel": level,
            "includeThoughts": True,
        },
    }


def system_instruction(prompt: str) -> dict[str, Any]:
    return {"parts": [{"text": prompt}]}


def reminder(text: str) -> str:
    return f"<system-reminder>\n{text}\n</system-reminder>"


def user(prompt: str, context: str | None = None) -> dict[str, Any]:
    text = f"{reminder(context)}\n\n{prompt}" if context else prompt
    return {"role": "user", "content": text}


def _extract_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({"text": item})
        elif isinstance(item, dict):
            # Сохраняем исходные части Gemini (рассуждения и сигнатуры) для сохранения контекста в истории
            if "thought" in item or "thoughtSignature" in item or "signature" in item:
                part_dict: dict[str, Any] = {}
                if "text" in item and item["text"]:
                    part_dict["text"] = item["text"]
                if item.get("thought") is True:
                    part_dict["thought"] = True
                sig = item.get("thoughtSignature") or item.get("signature")
                if sig:
                    part_dict["thoughtSignature"] = sig
                if part_dict:
                    parts.append(part_dict)
                continue

            item_type = item.get("type")
            if item_type == "text":
                text = item.get("text")
                if text:
                    parts.append({"text": text})
            elif item_type == "image":
                source = item.get("source") or {}
                if source.get("type") == "base64" and source.get("data"):
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": source.get("media_type") or "image/png",
                                "data": source.get("data"),
                            }
                        }
                    )
            elif "text" in item:
                parts.append({"text": str(item["text"])})
    return parts


def format_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []

    for msg in messages:
        raw_role = msg.get("role")
        role = "model" if raw_role in ("assistant", "model") else "user"
        parts = _extract_parts(msg.get("content"))
        if not parts:
            continue

        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})

    return contents


def build(
    *,
    model: str,
    prompt: str,
    messages: list[dict[str, Any]],
    effort: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    limit = max_tokens or settings.gemini_max_output_tokens
    return {
        "contents": format_contents(messages),
        "systemInstruction": system_instruction(prompt),
        "generationConfig": generation_config(effort, limit),
        "safetySettings": safety_settings(),
    }
