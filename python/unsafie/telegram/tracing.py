"""Spans for outgoing Bot API calls.

Everything the bot sends goes through the session middleware chain, so one hook covers
`sender.py`, the agent tools and aiogram's own internals alike — no call to Telegram can slip
out of a trace unnoticed.

Two methods are deliberately left out. `getUpdates` hangs for half a minute by design and would
add a span per poll forever, and `sendChatAction` repeats every five seconds for as long as the
agent is thinking; neither says anything a trace reader wants to know.
"""

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType

from unsafie import telemetry
from unsafie.telemetry import attrs

SILENT = {"GetUpdates", "SendChatAction"}
SERVER = "api.telegram.org"


def method_name(method: TelegramMethod) -> str:
    name = type(method).__name__
    return name[0].lower() + name[1:]


class ApiTracing(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if type(method).__name__ in SILENT:
            return await make_request(bot, method)
        api = method_name(method)
        with telemetry.span(
            f"tg.api {api}",
            kind=telemetry.CLIENT,
            attributes={
                "rpc.system": "telegram",
                "rpc.method": api,
                attrs.SERVER_ADDRESS: SERVER,
                attrs.TG_METHOD: api,
                attrs.BOT_ID: bot.id,
                attrs.CHAT_ID: getattr(method, "chat_id", None),
                attrs.MESSAGE_ID: getattr(method, "message_id", None),
            },
        ) as span:
            response = await make_request(bot, method)
            sent = getattr(response.result, "message_id", None)
            telemetry.set_attrs(span, {attrs.MESSAGE_ID: sent} if sent else None)
            return response
