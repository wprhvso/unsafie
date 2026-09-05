"""Context plumbing: the three cases where OpenTelemetry's implicit context is not enough.

`Anchor` — a span that is current *somewhere else*. The agent SDK calls our in-process MCP
tools from its own tasks, and a task copies contextvars when it is created, not when the tool
runs: without an explicit parent every tool call would land in the trace as a root of its own.

`detached()` — the opposite problem. A long-lived task (bot polling, a background loop) must
not inherit the span that happened to be current when it was started, or every update for the
next month becomes a child of one boot span.

`links()` — fire-and-forget work (a webhook accepted now, processed after the response is
already sent) gets its own trace, tied to the request by a link instead of a parent.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Link


class Anchor:
    """A mutable holder for the context a detached callback should continue from."""

    __slots__ = ("_context",)

    def __init__(self) -> None:
        self._context: Context | None = None

    def capture(self) -> None:
        self._context = otel_context.get_current()

    def release(self) -> None:
        self._context = None

    @property
    def context(self) -> Context | None:
        return self._context


@contextmanager
def detached() -> Iterator[None]:
    """Run with an empty context, so whatever starts here becomes a root of its own trace."""
    token = otel_context.attach(Context())
    try:
        yield
    finally:
        otel_context.detach(token)


@contextmanager
def muted() -> Iterator[None]:
    """Suppress auto-instrumentation: the idle polling queries of the loops are not events."""
    try:
        from opentelemetry.instrumentation.utils import suppress_instrumentation
    except ImportError:  # pragma: no cover - instrumentation package is optional
        yield
        return
    with suppress_instrumentation():
        yield


def links() -> list[Link]:
    """A link to the span that is current right now (empty when there is none)."""
    context = trace.get_current_span().get_span_context()
    return [Link(context)] if context.is_valid else []


def trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
