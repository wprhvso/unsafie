from opentelemetry.trace import SpanKind

from unsafie.telemetry.anchor import Anchor, detached, links, muted, trace_id
from unsafie.telemetry.attrs import clip, content
from unsafie.telemetry.helpers import (
    annotate,
    clean,
    context_of,
    current,
    event,
    fail,
    ids,
    refused,
    set_attrs,
    span,
    start,
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
    "Anchor",
    "annotate",
    "clean",
    "clip",
    "content",
    "context_of",
    "current",
    "detached",
    "enabled",
    "event",
    "fail",
    "flush",
    "ids",
    "instrument_app",
    "links",
    "muted",
    "refused",
    "set_attrs",
    "setup",
    "shutdown",
    "span",
    "start",
    "trace_id",
    "traced",
    "tracer",
]
