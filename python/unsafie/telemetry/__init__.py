"""Tracing for unsafie: one trace per event, no blank stretches inside it.

    from unsafie import telemetry
    from unsafie.telemetry import attrs

    with telemetry.span("ssh.exec", kind=telemetry.CLIENT, attributes={attrs.SSH_ALIAS: alias}):
        ...

Everything else — provider, exporter, context plumbing — lives in the sibling modules and is
re-exported here, so the rest of the codebase imports one name.
"""

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
    """FastAPI server spans; a no-op when tracing is off."""
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
