from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context


@contextmanager
def detached() -> Iterator[None]:
    token = otel_context.attach(Context())
    try:
        yield
    finally:
        otel_context.detach(token)


@contextmanager
def muted() -> Iterator[None]:
    try:
        from opentelemetry.instrumentation.utils import suppress_instrumentation
    except ImportError:  # pragma: no cover
        yield
        return
    with suppress_instrumentation():
        yield


def trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
