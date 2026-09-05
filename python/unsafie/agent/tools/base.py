import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from aiogram import Bot

from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository
from unsafie.errors import OpsError
from unsafie.github import metrics
from unsafie.log import short

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolContext:
    bot: Bot
    bot_id: int
    chat_id: int
    user_id: int
    turn_id: UUID
    locale: str = "en"

    @property
    def prefix(self) -> str:
        return f"bot={self.bot_id} chat={self.chat_id} user={self.user_id} turn={self.turn_id}"


async def current_turn(ctx: ToolContext) -> Turn | None:
    async with SessionLocal() as session:
        return await TurnRepository(session).get(ctx.turn_id)


Handler = Callable[[ToolContext, dict], Awaitable[dict]]


def text(value: str) -> dict:
    return {"content": [{"type": "text", "text": value}]}


def error(value: str) -> dict:
    return {"content": [{"type": "text", "text": value}], "is_error": True}


def json_result(data) -> dict:
    return text(json.dumps(data, ensure_ascii=False, indent=1))


def schema(required: list[str], **props) -> dict:
    types = {str: "string", int: "integer", bool: "boolean"}
    return {
        "type": "object",
        "properties": {k: {"type": types[v]} for k, v in props.items()},
        "required": required,
    }


_HANDLED: list[tuple[type[Exception], Callable[[Exception], str]]] = [(OpsError, str)]


def handle_errors(exc_type: type[Exception], formatter: Callable[[Exception], str]) -> None:
    _HANDLED.insert(0, (exc_type, formatter))


def guarded(fn: Handler) -> Handler:
    @functools.wraps(fn)
    async def wrapper(ctx: ToolContext, args: dict) -> dict:
        started = time.perf_counter()
        name = fn.__name__
        counters = metrics.start()
        logger.info("%s tool=%s args=%s", ctx.prefix, name, short(args, 500))
        try:
            result = await fn(ctx, args)
        except Exception as e:
            for exc_type, formatter in _HANDLED:
                if isinstance(e, exc_type):
                    logger.info("%s tool=%s refused: %s", ctx.prefix, name, e)
                    return error(formatter(e))
            raise
        traffic = metrics.summary(counters)
        logger.info(
            "%s tool=%s done in %.1fms%s",
            ctx.prefix,
            name,
            (time.perf_counter() - started) * 1000,
            f" [github: {traffic}]" if traffic else "",
        )
        return result

    return wrapper
