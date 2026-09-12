import logging
from typing import Any

from opentelemetry import trace


class TraceIds(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            record.otel = (
                f" trace={format(context.trace_id, '032x')} span={format(context.span_id, '016x')}"
            )
        else:
            record.otel = ""
        return True


def otel_trace_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict
