import json
import logging
import logging.config
import sys
from typing import Any

from unsafie.settings import settings
from unsafie.telemetry.logs import TraceIds

FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s [%(taskName)s]%(otel)s %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

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
        raise ValueError(f"LOG_LEVEL={settings.log_level!r}: unknown level")
    return value


def config() -> dict[str, Any]:
    loggers: dict[str, Any] = {
        name: {"level": lvl, "handlers": [], "propagate": True} for name, lvl in THIRD_PARTY.items()
    }
    loggers["sqlalchemy.engine"] = {
        "level": "INFO" if settings.sql_echo else "WARNING",
        "handlers": [],
        "propagate": True,
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": FORMAT, "datefmt": DATEFMT}},
        "filters": {"trace": {"()": TraceIds}},
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "filters": ["trace"],
                "stream": sys.stderr,
            }
        },
        "root": {"level": level(), "handlers": ["stderr"]},
        "loggers": loggers,
    }


def setup() -> None:
    global _configured
    if _configured:
        return
    logging.config.dictConfig(config())
    logging.captureWarnings(True)
    _configured = True
    logging.getLogger(__name__).info(
        "logging configured level=%s sql_echo=%s truncate=%s",
        level(),
        settings.sql_echo,
        settings.log_truncate,
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
