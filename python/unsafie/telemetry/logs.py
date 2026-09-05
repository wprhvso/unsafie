"""Trace ids in every log line.

Grafana already knows how to jump from a log to a trace and back (the `trace_id` derived field
of the VictoriaLogs datasource); it only needs the id to be printed. `%(otel)s` is empty outside
a trace, so the format stays readable in tests and in the CLI.
"""

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
