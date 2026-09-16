from __future__ import annotations

from typing import Any


class LLMResponse(str):
    @property
    def content(self) -> str:
        return str(self)

    @property
    def text(self) -> str:
        return str(self)


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item or (item.get("type") == "text" and "text" in item):
                    parts.append(str(item["text"]))
        return "\n".join(parts)
    return str(content) if content is not None else ""


def format_chat_prompt(messages_or_prompt: Any, system_instruction: str = "") -> str:
    if isinstance(messages_or_prompt, str):
        text = messages_or_prompt.strip()
        if "**USER**:" in text or "**SYSTEM**:" in text or "**MODEL**:" in text:
            return text
        if system_instruction:
            return f"**SYSTEM**:\n{system_instruction}\n\n**USER**:\n{text}\n\n**MODEL**:\n"
        return f"**USER**:\n{text}\n\n**MODEL**:\n"

    if isinstance(messages_or_prompt, dict):
        sys_inst = ""
        raw_sys = messages_or_prompt.get("systemInstruction")
        if isinstance(raw_sys, dict):
            sys_parts = raw_sys.get("parts", [])
            if sys_parts and isinstance(sys_parts[0], dict) and "text" in sys_parts[0]:
                sys_inst = str(sys_parts[0]["text"])
        elif isinstance(raw_sys, str):
            sys_inst = raw_sys

        contents = messages_or_prompt.get("contents")
        if isinstance(contents, list):
            return format_chat_prompt(contents, system_instruction=sys_inst or system_instruction)

    parts: list[str] = []
    if system_instruction:
        parts.append(f"**SYSTEM**:\n{system_instruction}")

    if isinstance(messages_or_prompt, list):
        for msg in messages_or_prompt:
            role = "user"
            content = ""

            if isinstance(msg, dict):
                role = str(msg.get("role", "user")).lower()
                raw_content = msg.get("content")
                if raw_content is None and "parts" in msg:
                    raw_content = msg.get("parts")
                content = _extract_text(raw_content)
            elif hasattr(msg, "role") and hasattr(msg, "content"):
                role = str(getattr(msg, "role", "user")).lower()
                content = _extract_text(getattr(msg, "content", ""))
            elif hasattr(msg, "type") and hasattr(msg, "content"):
                role = str(getattr(msg, "type", "user")).lower()
                content = _extract_text(getattr(msg, "content", ""))
            elif isinstance(msg, (tuple, list)) and len(msg) == 2:
                role, content = str(msg[0]).lower(), _extract_text(msg[1])
            else:
                content = str(msg)

            if role in ("system", "developer"):
                parts.append(f"**SYSTEM**:\n{content}")
            elif role in ("assistant", "model", "ai", "bot"):
                parts.append(f"**MODEL**:\n{content}")
            elif role in ("tool", "function"):
                parts.append(f"**USER**:\n[TOOL RESULT]:\n{content}")
            else:
                parts.append(f"**USER**:\n{content}")

    prompt = "\n\n".join(parts)
    if parts and not parts[-1].startswith("**MODEL**:"):
        prompt += "\n\n**MODEL**:\n"
    return prompt


def clean_model_response(text: str) -> LLMResponse:
    cleaned = text.strip()
    prefixes = (
        "**MODEL**:",
        "**MODEL** :",
        "MODEL:",
        "**Assistant**:",
        "Assistant:",
        "**AI**:",
        "AI:",
    )
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return LLMResponse(cleaned)
