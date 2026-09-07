import logging
import time
from typing import Any

from opentelemetry.trace import Span

from unsafie import telemetry
from unsafie.log import short
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

CALL_BLOCKS = ("tool_use", "server_tool_use")
THINKING_BLOCKS = ("thinking", "redacted_thinking")


def log_reply(reply, prefix: str) -> None:
    logger.info(
        "%s model=%s stop=%s blocks=%s",
        prefix,
        reply.model,
        reply.stop_reason,
        len(reply.content),
    )
    for index, block in enumerate(reply.content):
        kind = block.get("type")
        if kind == "text":
            logger.info("%s block[%s] text: %s", prefix, index, short(block.get("text")))
        elif kind in THINKING_BLOCKS:
            logger.debug("%s block[%s] thinking: %s", prefix, index, short(block.get("thinking")))
        elif kind in CALL_BLOCKS:
            logger.info(
                "%s block[%s] %s id=%s name=%s input=%s",
                prefix,
                index,
                kind,
                block.get("id"),
                block.get("name"),
                short(block.get("input")),
            )
        else:
            logger.debug("%s block[%s] %s: %s", prefix, index, kind, short(block))


class Recorder:
    def __init__(self, prefix: str, span: Span) -> None:
        self.prefix = prefix
        self.span = span
        self.parent = telemetry.context_of(span)
        self.steps = 0
        self._mark = time.time_ns()

    def request(self, step: int, messages: int, tools: int) -> None:
        self.steps = step
        self._mark = time.time_ns()
        logger.info("%s step=%s messages=%s tools=%s", self.prefix, step, messages, tools)

    def reply(self, reply) -> None:
        log_reply(reply, f"{self.prefix} step#{self.steps}")
        calls = [b.get("name") for b in reply.content if b.get("type") in CALL_BLOCKS]
        text = "".join(b.get("text", "") for b in reply.content if b.get("type") == "text")
        thinking = any(b.get("type") in THINKING_BLOCKS for b in reply.content)
        usage = reply.usage or {}
        self._interval(
            "gen_ai.completion",
            {
                attrs.GEN_AI_SYSTEM: "anthropic",
                attrs.GEN_AI_OPERATION: "chat",
                attrs.GEN_AI_RESPONSE_MODEL: reply.model,
                attrs.BLOCKS: len(reply.content),
                attrs.TOOL_CALLS: calls or None,
                attrs.ATTEMPT: self.steps,
                "unsafie.thinking": thinking or None,
                attrs.GEN_AI_INPUT_TOKENS: usage.get("input_tokens"),
                attrs.GEN_AI_OUTPUT_TOKENS: usage.get("output_tokens"),
                "gen_ai.usage.cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                "gen_ai.usage.cache_creation_input_tokens": usage.get(
                    "cache_creation_input_tokens"
                ),
                attrs.GEN_AI_FINISH_REASONS: [reply.stop_reason] if reply.stop_reason else None,
                attrs.COMPLETION: telemetry.content(text) if text else None,
            },
            kind=telemetry.CLIENT,
        )

    def _interval(self, name: str, attributes: dict, kind=telemetry.INTERNAL) -> None:
        now = time.time_ns()
        span = telemetry.start(
            name, kind=kind, parent=self.parent, attributes=attributes, start_time=self._mark
        )
        span.end(now)
        self._mark = now

    def note(self, name: str, attributes: dict | None = None) -> None:
        if self.span.is_recording():
            self.span.add_event(name, telemetry.clean(attributes))

    def annotate(self, **attributes: Any) -> None:
        telemetry.set_attrs(self.span, attributes)
