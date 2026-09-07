from opentelemetry.trace import SpanKind

from unsafie.telemetry.attrs import clip, content
from unsafie.telemetry.context import detached, muted, trace_id
from unsafie.telemetry.helpers import (
    annotate,
    clean,
    current,
    event,
    fail,
    refused,
    set_attrs,
    span,
    traced,
    tracer,
)
from unsafie.telemetry.provider import enabled, flush, setup, shutdown

CLIENT = SpanKind.CLIENT
CONSUMER = SpanKind.CONSUMER
INTERNAL = SpanKind.INTERNAL
PRODUCER = SpanKind.PRODUCER
SERVER = SpanKind.SERVER


def instrument_app(app) -> None:
    if not enabled():
        return
    from unsafie.telemetry import instrument

    instrument.app(app)


__all__ = [
    "CLIENT",
    "CONSUMER",
    "INTERNAL",
    "PRODUCER",
    "SERVER",
    "annotate",
    "clean",
    "clip",
    "content",
    "current",
    "detached",
    "enabled",
    "event",
    "fail",
    "flush",
    "instrument_app",
    "muted",
    "refused",
    "set_attrs",
    "setup",
    "shutdown",
    "span",
    "trace_id",
    "traced",
    "tracer",
]
