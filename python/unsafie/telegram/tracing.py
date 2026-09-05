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


def sent_message_id(response) -> int | None:
    """The id of what was just sent, whatever shape the call returned.

    The middleware chain hands over the unwrapped result, not the `Response` envelope, and a
    result is anything a Bot API method can return: a `Message`, a `User` from `getMe`, a list
    from `sendMediaGroup`, a bare `True`. Only the first two lines of that list carry an id.
    """
    result = getattr(response, "result", response)
    if isinstance(result, list):
        result = result[0] if result else None
    value = getattr(result, "message_id", None)
    return value if isinstance(value, int) else None


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
            sent = sent_message_id(response)
            telemetry.set_attrs(span, {attrs.MESSAGE_ID: sent} if sent else None)
            return response
