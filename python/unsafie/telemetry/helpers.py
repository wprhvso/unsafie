import asyncio
import functools
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Link, Span, SpanKind, Status, StatusCode

from unsafie.errors import OpsError
from unsafie.telemetry import attrs

SCOPE = "unsafie"

Attributes = Mapping[str, Any] | None


def tracer() -> trace.Tracer:
    return trace.get_tracer(SCOPE)


def clean(attributes: Attributes) -> dict[str, Any]:
    return {k: v for k, v in (attributes or {}).items() if v is not None}


def fail(span: Span, exc: BaseException) -> None:
    if isinstance(exc, asyncio.CancelledError):
        span.set_attribute(attrs.CANCELLED, True)
        return
    if isinstance(exc, OpsError):
        refused(span, exc)
        return
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, attrs.clip(f"{type(exc).__name__}: {exc}", 500)))


def refused(span: Span, exc: BaseException | str) -> None:
    span.set_attribute(attrs.REFUSED, True)
    span.set_attribute(attrs.REFUSAL, attrs.clip(str(exc), 500))


@contextmanager
def span(
    name: str,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Attributes = None,
    parent: Context | None = None,
    links: list[Link] | None = None,
    start_time: int | None = None,
) -> Iterator[Span]:
    with tracer().start_as_current_span(
        name,
        context=parent,
        kind=kind,
        attributes=clean(attributes),
        links=links,
        start_time=start_time,
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        try:
            yield current
        except BaseException as exc:
            fail(current, exc)
            raise


def start(
    name: str,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Attributes = None,
    parent: Context | None = None,
    start_time: int | None = None,
) -> Span:
    return tracer().start_span(
        name,
        context=parent,
        kind=kind,
        attributes=clean(attributes),
        start_time=start_time,
        record_exception=False,
        set_status_on_exception=False,
    )


def traced(
    name: str | None = None,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Attributes = None,
) -> Callable:

    def decorator(fn):
        span_name = name or f"{fn.__module__.rsplit('.', 1)[-1]}.{fn.__name__}"

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            with span(span_name, kind=kind, attributes=attributes):
                return await fn(*args, **kwargs)

        return wrapper

    return decorator


def current() -> Span:
    return trace.get_current_span()


def context_of(span: Span) -> Context:
    return trace.set_span_in_context(span)


def annotate(**attributes: Any) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        for key, value in clean(attributes).items():
            span.set_attribute(key, value)


def set_attrs(span: Span, attributes: Attributes) -> None:
    if span.is_recording():
        for key, value in clean(attributes).items():
            span.set_attribute(key, value)


def event(name: str, attributes: Attributes = None) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.add_event(name, clean(attributes))


def ids() -> tuple[str, str] | None:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")
