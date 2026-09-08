"""The unsafie SDK: everything the agent and a human can do, as plain python.

Inside the agent's REPL every name below is already imported. On a laptop:

    pip install unsafie-sdk        # or uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=uns_…     # the bot gives you one with /auth
    python -c "import unsafie_sdk as u; u.chat.send('hi'); u.stop()"

Everything lives in a module: chat, machines, browser, github, pages, packages, plus stop().
"""

from unsafie_sdk import browser, chat, github, machines, packages, pages
from unsafie_sdk.client import Client, client, setting
from unsafie_sdk.errors import (
    LimitReached,
    NotAuthorized,
    NotFound,
    Refused,
    StopTurn,
    UnsafieError,
)
from unsafie_sdk.stop import stop


def me() -> dict:
    """Who this token belongs to, which machine it drives and what the limits are."""
    return client().call("GET", "/me")


__all__ = [
    "Client",
    "LimitReached",
    "NotAuthorized",
    "NotFound",
    "Refused",
    "StopTurn",
    "UnsafieError",
    "browser",
    "chat",
    "client",
    "github",
    "machines",
    "me",
    "packages",
    "pages",
    "setting",
    "stop",
]
