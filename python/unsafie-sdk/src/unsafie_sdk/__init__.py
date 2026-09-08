"""The unsafie SDK: everything the agent and a human can do, as plain python.

Inside the agent's REPL every name below is already imported. On a laptop:

    pip install unsafie-sdk        # or uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=uns_…     # the bot gives you one with /auth
    python -c "import unsafie_sdk as u; u.say('hi')"

The full map lives in the description of the `python` tool — that is the one place
the agent reads it from, so it never drifts from what the library actually does.
"""

from unsafie_sdk import (
    automation,
    browser,
    chat,
    ci,
    github,
    machines,
    net,
    pages,
    store,
)
from unsafie_sdk.chat import file, note, photo, say
from unsafie_sdk.client import Client, client, setting
from unsafie_sdk.errors import (
    LimitReached,
    NotAuthorized,
    NotFound,
    Refused,
    UnsafieError,
)
from unsafie_sdk.machines import fan, release, run, submit, take
from unsafie_sdk.net import fetch
from unsafie_sdk.packages import install
from unsafie_sdk.store import kv, secrets

page = pages.create


def me() -> dict:
    """Who this token belongs to, which machine it drives and what the limits are."""
    return client().call("GET", "/me")


def quota() -> dict:
    """Machines, minutes and priority left for this account today."""
    return machines.quota()


__all__ = [
    "Client",
    "LimitReached",
    "NotAuthorized",
    "NotFound",
    "Refused",
    "UnsafieError",
    "automation",
    "browser",
    "chat",
    "ci",
    "client",
    "fan",
    "fetch",
    "file",
    "github",
    "install",
    "kv",
    "machines",
    "me",
    "net",
    "note",
    "page",
    "pages",
    "photo",
    "quota",
    "release",
    "run",
    "say",
    "secrets",
    "setting",
    "store",
    "submit",
    "take",
]
