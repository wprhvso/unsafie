"""TracerProvider wiring: resource, sampler, limits, exporter, shutdown.

Tracing is optional at runtime. With `OTEL_ENABLED=0` no provider is installed, the global
tracer stays the no-op one, and every `span()` in the codebase costs one attribute lookup —
so the instrumentation can stay in the code unconditionally.
"""

import logging
import os
import socket

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, Sampler, TraceIdRatioBased

from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

MAX_ATTRIBUTES = 128
MAX_EVENTS = 128
MAX_LINKS = 32

_provider: TracerProvider | None = None
_configured = False


def version() -> str:
    if settings.service_version:
        return settings.service_version
    try:
        from importlib.metadata import version as installed

        return installed("unsafie")
    except Exception:
        return "unknown"


def resource() -> Resource:
    host = socket.gethostname()
    return Resource.create(
        {
            attrs.SERVICE_NAME: settings.service_name,
            attrs.SERVICE_VERSION: version(),
            attrs.SERVICE_INSTANCE: f"{host}:{os.getpid()}",
            attrs.ENVIRONMENT: settings.environment,
            attrs.HOST_NAME: host,
            attrs.PROCESS_PID: os.getpid(),
        }
    )


def sampler() -> Sampler:
    """Parent-based: a sampling decision made upstream is never overturned downstream."""
    ratio = min(max(settings.otel_sample_ratio, 0.0), 1.0)
    return ParentBased(ALWAYS_ON if ratio >= 1.0 else TraceIdRatioBased(ratio))


def endpoint() -> str:
    """OTLP/HTTP needs the full path — VictoriaTraces does not serve the default /v1/traces."""
    url = settings.otel_endpoint.rstrip("/")
    if not settings.otel_protocol.startswith("http"):
        return url
    return url if url.endswith("/v1/traces") else url + settings.otel_traces_path


def exporter():
    """gRPC by default; OTLP/HTTP is the escape hatch when grpcio is not an option."""
    url = endpoint()
    if settings.otel_protocol.startswith("http"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(endpoint=url, timeout=settings.otel_export_timeout)
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as Grpc

    return Grpc(endpoint=url, insecure=url.startswith("http://"), timeout=settings.otel_export_timeout)


def setup() -> None:
    """Idempotent: uvicorn imports the app module and `python -m unsafie` calls this too."""
    global _provider, _configured
    if _configured:
        return
    _configured = True
    if not settings.otel_enabled:
        logger.info("tracing disabled (OTEL_ENABLED=0)")
        return
    try:
        provider = TracerProvider(
            resource=resource(),
            sampler=sampler(),
            span_limits=SpanLimits(
                max_attributes=MAX_ATTRIBUTES,
                max_events=MAX_EVENTS,
                max_links=MAX_LINKS,
                max_attribute_length=settings.otel_max_attr_len,
            ),
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter(),
                max_queue_size=settings.otel_queue_size,
                max_export_batch_size=settings.otel_batch_size,
                schedule_delay_millis=settings.otel_schedule_delay,
            )
        )
    except Exception:
        # Traces are nice to have; a broken exporter must never keep the bot from starting.
        logger.exception("tracing setup failed, continuing without traces")
        return
    trace.set_tracer_provider(provider)
    _provider = provider

    from unsafie.telemetry import instrument

    instrument.everything()
    logger.info(
        "tracing -> %s (%s) service=%s version=%s env=%s sample=%s content=%s",
        endpoint(),
        settings.otel_protocol,
        settings.service_name,
        version(),
        settings.environment,
        settings.otel_sample_ratio,
        settings.otel_capture_content,
    )


def flush(timeout_ms: int = 5000) -> None:
    if _provider is not None:
        _provider.force_flush(timeout_ms)


def shutdown() -> None:
    """Flush what is still queued: the last spans of a shutdown are the interesting ones."""
    global _provider
    if _provider is None:
        return
    try:
        _provider.shutdown()
    except Exception:
        logger.warning("tracing shutdown failed", exc_info=True)
    _provider = None
    logger.info("tracing flushed and stopped")


def enabled() -> bool:
    return _provider is not None
