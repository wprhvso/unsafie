import asyncio
import functools
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from unsafie.errors import OpsError
from unsafie.telemetry import attrs

SCOPE = "unsafie"

Attributes = Mapping[str, Any] | None


def tracer() -> trace.Tracer:
    return trace.get_tracer(SCOPE)


def _clean_val(v: Any) -> Any:
    if isinstance(v, (bool, str, bytes, int, float)):
        return v
    if isinstance(v, (list, tuple)):
        if all(isinstance(x, (bool, str, bytes, int, float)) for x in v):
            return v
    return json.dumps(v, ensure_ascii=False, default=str)


def clean(attributes: Attributes) -> dict[str, Any]:
    return {k: _clean_val(v) for k, v in (attributes or {}).items() if v is not None}


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
) -> Iterator[Span]:
    with tracer().start_as_current_span(
        name,
        kind=kind,
        attributes=clean(attributes),
        record_exception=False,
        set_status_on_exception=False,
    ) as current_span:
        try:
            yield current_span
        except BaseException as exc:
            fail(current_span, exc)
            raise


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


def annotate(**attributes: Any) -> None:
    live = trace.get_current_span()
    if live.is_recording():
        for key, value in clean(attributes).items():
            live.set_attribute(key, value)


def set_attrs(span: Span, attributes: Attributes) -> None:
    if span.is_recording():
        for key, value in clean(attributes).items():
            span.set_attribute(key, value)


def event(name: str, attributes: Attributes = None) -> None:
    live = trace.get_current_span()
    if live.is_recording():
        live.add_event(name, clean(attributes))
