"""What the agent did, as logs and as spans.

`query()` spends its minutes inside the `claude` CLI — a subprocess nobody here can instrument.
What crosses the boundary is a stream of messages and the tool hooks, and between them they
account for the whole wall clock: a span for every stretch the model was writing, a span for
every tool it ran. Without this the agent is one flat span with minutes of nothing inside.

The spans are opened with an explicit parent and explicit timestamps: the hooks run in tasks of
the SDK, where neither the current context nor "now" is what we mean.
"""

import logging
import time
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from opentelemetry.trace import Span

from unsafie import telemetry
from unsafie.log import short
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

MAX_OPEN_TOOLS = 64


def _log_blocks(tag: str, blocks, prefix: str) -> None:
    for i, block in enumerate(blocks):
        if isinstance(block, TextBlock):
            logger.info("%s %s block[%s] text: %s", prefix, tag, i, short(block.text))
        elif isinstance(block, ThinkingBlock):
            logger.debug("%s %s block[%s] thinking: %s", prefix, tag, i, short(block.thinking))
        elif isinstance(block, ToolUseBlock):
            logger.info(
                "%s %s block[%s] tool_use id=%s name=%s input=%s",
                prefix,
                tag,
                i,
                block.id,
                block.name,
                short(block.input),
            )
        elif isinstance(block, ToolResultBlock):
            logger.info(
                "%s %s block[%s] tool_result for=%s is_error=%s content=%s",
                prefix,
                tag,
                i,
                block.tool_use_id,
                block.is_error,
                short(block.content),
            )
        else:
            logger.debug(
                "%s %s block[%s] %s: %s", prefix, tag, i, type(block).__name__, short(block)
            )


def log_sdk_message(m, prefix: str) -> None:
    if isinstance(m, AssistantMessage):
        logger.info("%s assistant model=%s blocks=%s", prefix, m.model, len(m.content))
        _log_blocks("assistant", m.content, prefix)
    elif isinstance(m, UserMessage):
        if isinstance(m.content, str):
            logger.info("%s user text: %s", prefix, short(m.content))
        else:
            _log_blocks("user", m.content, prefix)
    elif isinstance(m, SystemMessage):
        logger.info("%s system subtype=%s data=%s", prefix, m.subtype, short(m.data))
    elif isinstance(m, ResultMessage):
        logger.info(
            "%s result subtype=%s is_error=%s turns=%s duration=%sms session=%s cost=%s",
            prefix,
            m.subtype,
            m.is_error,
            m.num_turns,
            m.duration_ms,
            m.session_id,
            m.total_cost_usd,
        )
    else:
        logger.debug("%s %s: %s", prefix, type(m).__name__, short(m))


class Recorder:
    """Fills one `gen_ai.invoke_agent` span with what happened inside the CLI."""

    def __init__(self, prefix: str, span: Span) -> None:
        self.prefix = prefix
        self.span = span
        self.parent = telemetry.context_of(span)
        self.count = 0
        self._mark = time.time_ns()
        self._open: dict[str, Span] = {}

    # -- the message stream ------------------------------------------------------------------

    def message(self, m: Any) -> None:
        self.count += 1
        log_sdk_message(m, f"{self.prefix} sdk#{self.count}")
        if isinstance(m, SystemMessage) and m.subtype == "init":
            self._interval("gen_ai.session.init", {"gen_ai.conversation.id": m.data.get("session_id")})
        elif isinstance(m, AssistantMessage):
            self._completion(m)
        elif isinstance(m, ResultMessage):
            self._mark = time.time_ns()

    def _completion(self, m: AssistantMessage) -> None:
        """The stretch since the previous event is the model writing this message."""
        calls = [b.name for b in m.content if isinstance(b, ToolUseBlock)]
        text = "".join(b.text for b in m.content if isinstance(b, TextBlock))
        thinking = any(isinstance(b, ThinkingBlock) for b in m.content)
        self._interval(
            "gen_ai.completion",
            {
                attrs.GEN_AI_SYSTEM: "anthropic",
                attrs.GEN_AI_OPERATION: "chat",
                attrs.GEN_AI_RESPONSE_MODEL: m.model,
                attrs.BLOCKS: len(m.content),
                attrs.TOOL_CALLS: calls or None,
                "unsafie.thinking": thinking or None,
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

    # -- tool hooks --------------------------------------------------------------------------

    def tool_started(self, name: str | None, tool_input: Any, tool_use_id: str | None) -> None:
        """PreToolUse. Our own MCP tools open their own span in `agent.tools.base.guarded`."""
        if not name or name.startswith("mcp__") or len(self._open) >= MAX_OPEN_TOOLS:
            return
        self._mark = time.time_ns()
        self._open[tool_use_id or name] = telemetry.start(
            f"gen_ai.tool {name}",
            parent=self.parent,
            start_time=self._mark,
            attributes={
                attrs.GEN_AI_OPERATION: "execute_tool",
                attrs.GEN_AI_TOOL_NAME: name,
                attrs.GEN_AI_TOOL_CALL_ID: tool_use_id,
                attrs.TOOL: name,
                attrs.TOOL_SOURCE: "claude",
                attrs.TOOL_ARGS: telemetry.content(tool_input),
            },
        )

    def tool_finished(self, name: str | None, tool_use_id: str | None, response: Any) -> None:
        """PostToolUse."""
        span = self._open.pop(tool_use_id or name or "", None)
        if span is None:
            return
        telemetry.set_attrs(span, {attrs.TOOL_RESULT: telemetry.content(response)})
        self._mark = time.time_ns()
        span.end(self._mark)

    def note(self, name: str, attributes: dict | None = None) -> None:
        """An event on the agent span itself — the Stop hook, an injected message."""
        if self.span.is_recording():
            self.span.add_event(name, telemetry.clean(attributes))

    def close(self) -> None:
        """A tool whose PostToolUse never arrived (denied, crashed) must not leak a span."""
        for key, span in self._open.items():
            span.set_attribute(attrs.TOOL_ERROR, True)
            span.set_attribute(attrs.REFUSAL, "no PostToolUse for " + key)
            span.end()
        self._open.clear()
