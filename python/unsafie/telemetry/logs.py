import logging

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
