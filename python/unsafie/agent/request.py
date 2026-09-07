import logging

from unsafie.agent.prompt import SYSTEM_PROMPT
from unsafie.settings import settings

logger = logging.getLogger(__name__)

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "low"
UNCACHEABLE = frozenset({"thinking", "redacted_thinking"})
DOWNGRADABLE = ("thinking", "effort", "output_config", "context_management", "fallbacks")

_unsupported: dict[str, set[str]] = {}


def cache_control() -> dict:
    return {"type": "ephemeral", "ttl": settings.cache_ttl}


def system() -> list[dict]:
    return [
        {
            "type": "text",
            "text": "You are a Claude agent, built on Anthropic's Claude Agent SDK.",
            "cache_control": cache_control(),
        },
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": cache_control()},
    ]


def reminder(text: str) -> dict:
    return {"type": "text", "text": f"<system-reminder>\n{text}\n</system-reminder>"}


def user(prompt: str, context: str | None = None) -> dict:
    content: list[dict] = []
    if context:
        content.append(reminder(context))
    content.append({"type": "text", "text": prompt})
    return {"role": "user", "content": content}


def tools(definitions: list[dict]) -> list[dict]:
    out = list(definitions)
    if settings.claude_web_search:
        out.append(
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": settings.claude_web_search_max_uses,
            }
        )
    return out


def thinking() -> dict | None:
    mode = (settings.claude_thinking or "adaptive").strip().lower()
    if mode in ("", "off", "none", "0"):
        return None
    if mode == "adaptive":
        config: dict = {"type": "adaptive"}
        if settings.claude_thinking_display:
            config["display"] = settings.claude_thinking_display
        return config
    if mode.isdigit():
        return {"type": "enabled", "budget_tokens": int(mode)}
    logger.warning(
        "CLAUDE_THINKING=%r is not understood, falling back to adaptive", settings.claude_thinking
    )
    return {"type": "adaptive", "display": settings.claude_thinking_display}


def context_management() -> dict | None:
    if not settings.claude_clear_thinking:
        return None
    return {
        "edits": [{"type": "clear_thinking_20251015", "keep": settings.claude_clear_thinking_keep}]
    }


def fallbacks() -> str | None:
    value = (settings.claude_fallbacks or "").strip()
    return value or None


def anchors(messages: list[dict], previous: int) -> set[int]:
    last = len(messages) - 1
    if last < 0:
        return set()
    marks = {last}
    if 0 <= previous < last:
        marks.add(previous)
    return marks


def cached(messages: list[dict], marks: set[int]) -> list[dict]:
    out: list[dict] = []
    for index, message in enumerate(messages):
        content = message.get("content")
        if index not in marks or not isinstance(content, list):
            out.append(message)
            continue
        target = None
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") not in UNCACHEABLE:
                target = block
                break
        if target is None:
            out.append(message)
            continue
        blocks = [
            {**block, "cache_control": cache_control()} if block is target else block
            for block in content
        ]
        out.append({**message, "content": blocks})
    return out


def build(
    *,
    model: str,
    messages: list[dict],
    marks: set[int],
    definitions: list[dict],
    effort: str | None,
    max_tokens: int,
) -> dict:
    blocked = _unsupported.get(model, frozenset())
    body: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "system": system(),
        "messages": cached(messages, marks),
    }
    body["tools"] = definitions if definitions else []
    if effort and not ({"effort", "output_config"} & blocked):
        body["output_config"] = {"effort": effort}
    config = thinking()
    if config is not None and "thinking" not in blocked:
        body["thinking"] = config
        edits = context_management()
        if edits is not None and "context_management" not in blocked:
            body["context_management"] = edits
    mode = fallbacks()
    if mode is not None and "fallbacks" not in blocked:
        body["fallbacks"] = mode
    return body


def downgrade(model: str, error) -> bool:
    if error.status != 400:
        return False
    text = (error.message or "").lower()
    hit = {field for field in DOWNGRADABLE if field in text}
    if not hit:
        return False
    known = _unsupported.setdefault(model, set())
    fresh = hit - known
    if not fresh:
        return False
    known |= fresh
    logger.warning("%s rejects %s, retrying without it", model, ", ".join(sorted(fresh)))
    return True
