import logging

logger = logging.getLogger(__name__)

# /health is a probe, and the SSE stream would otherwise be one hour-long server span.
EXCLUDED_URLS = "health,api/admin/events"

_app_instrumented = False


def everything() -> None:
    _sqlalchemy()


def _sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from unsafie.database import engine

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    except Exception:
        logger.warning("sqlalchemy instrumentation skipped", exc_info=True)


def app(fastapi_app) -> None:
    global _app_instrumented
    if _app_instrumented:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Without exclude_spans every request drags three "http send" spans along with it.
        FastAPIInstrumentor.instrument_app(
            fastapi_app, excluded_urls=EXCLUDED_URLS, exclude_spans=["receive", "send"]
        )
        _app_instrumented = True
    except Exception:
        logger.warning("fastapi instrumentation skipped", exc_info=True)
