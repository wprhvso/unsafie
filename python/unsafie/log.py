import json
import logging
import logging.config
import re
import sys
from typing import Any

import orjson
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, unbind_contextvars

from unsafie.settings import settings
from unsafie.telemetry.logs import TraceIds, otel_trace_processor

_SECRET_KEYS = frozenset(
    {
        "token",
        "secret",
        "password",
        "api_key",
        "access_token",
        "private_key",
        "authorization",
        "admin_token",
        "telegram_webhook_secret",
    }
)

_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-zA-Z0-9_\-\.]{12,}|bot\d+:[a-zA-Z0-9_\-]{20,}|ghp_[a-zA-Z0-9]{30,})"
)

THIRD_PARTY: dict[str, str] = {
    "aiogram": "INFO",
    "aiogram.event": "WARNING",
    "alembic": "INFO",
    "httpx": "WARNING",
    "httpcore": "WARNING",
    "aiohttp": "WARNING",
    "asyncio": "WARNING",
    "asyncssh": "WARNING",
    "watchfiles": "WARNING",
    "opentelemetry": "WARNING",
    "uvicorn": "INFO",
    "uvicorn.error": "INFO",
    "uvicorn.access": "WARNING",
}

_configured = False


def level() -> str:
    value = settings.log_level.upper()
    if value not in logging.getLevelNamesMapping():
        msg = f"LOG_LEVEL={settings.log_level!r}: unknown level"
        raise ValueError(msg)
    return value


def scrub_secrets_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    for key, val in list(event_dict.items()):
        if any(secret in key.lower() for secret in _SECRET_KEYS):
            event_dict[key] = "***MASKED***"
        elif isinstance(val, str) and len(val) > 16:
            event_dict[key] = _SECRET_PATTERN.sub("***MASKED***", val)
    return event_dict


def ensure_message_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    if "event" in event_dict and "message" not in event_dict:
        event_dict["message"] = event_dict["event"]
    elif "message" in event_dict and "event" not in event_dict:
        event_dict["event"] = event_dict["message"]
    return event_dict


def _orjson_dumps(obj: Any, default: Any = None) -> str:
    return orjson.dumps(obj, default=default or str).decode("utf-8")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def setup() -> None:
    global _configured
    if _configured:
        return

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        otel_trace_processor,
        scrub_secrets_processor,
        ensure_message_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    use_console = settings.log_format == "console" or (
        settings.environment == "dev" and sys.stderr.isatty()
    )

    renderer = (
        structlog.dev.ConsoleRenderer(colors=True)
        if use_console
        else structlog.processors.JSONRenderer(serializer=_orjson_dumps)
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.ExtraAdder(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            otel_trace_processor,
            scrub_secrets_processor,
            ensure_message_processor,
            structlog.processors.format_exc_info,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level())
    root_logger.handlers = [handler]

    for name, lvl in THIRD_PARTY.items():
        sub_logger = logging.getLogger(name)
        sub_logger.setLevel(lvl)
        sub_logger.handlers = []
        sub_logger.propagate = True

    sql_logger = logging.getLogger("sqlalchemy.engine")
    sql_logger.setLevel("INFO" if settings.sql_echo else "WARNING")
    sql_logger.handlers = []
    sql_logger.propagate = True

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.captureWarnings(True)
    _configured = True
    get_logger(__name__).info(
        "logging.configured",
        level=level(),
        sql_echo=settings.sql_echo,
        truncate=settings.log_truncate,
        format=settings.log_format,
    )


def short(value: Any, limit: int | None = None) -> str:
    limit = limit or settings.log_truncate
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            value = repr(value)
    if len(value) <= limit:
        return value
    return f"{value[:limit]}…(+{len(value) - limit} chars)"
