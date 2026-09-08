"""The unsafie SDK: everything the agent and a human can do, as plain python.

Inside the agent's REPL every name below is already imported. On a laptop:

    pip install unsafie-sdk        # or uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=uns_…     # the bot gives you one with /auth
    python -c "import unsafie_sdk as u; u.say('hi')"
"""

from unsafie_sdk import (
    automation,
    browser,
    chat,
    ci,
    github,
    machines,
    net,
    packages,
    pages,
    ssh,
    store,
)
from unsafie_sdk.chat import file, note, photo, progress, say
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
from unsafie_sdk.packages import install, setup
from unsafie_sdk.store import kv, secrets

chrome = browser
page = pages.create


def me() -> dict:
    """Who this token belongs to, which machine it drives and what the limits are."""
    return client().call("GET", "/me")


def quota() -> dict:
    """Machines, minutes and priority left for this account today."""
    return machines.quota()


MAP = {
    "say(text, reply_to=None, buttons=None, silent=False)": "message into the chat — this is how the user hears from you",
    "note(text)": "a line into the live log, visible to the human, not to the chat",
    "page(markdown, title=None) -> url": "publish a long result as a web page",
    "file(path|bytes, caption=None, kind='document')": "send a file; photo(...) for pictures",
    "run(command, machine=None, timeout=None) -> Run": "shell on a pool machine; .output, .exit_code, .ok, .check()",
    "take(n) / release(name) / machines.listing()": "machines: single use, releasing destroys them",
    "fan(command) / submit(command) / machines.logs(job)": "same command everywhere, or in the background",
    "install('pandas')": "install python packages into this interpreter with uv, right now",
    "github.logins() / github.use(login) / github.token(repo)": "several accounts; pick one by username",
    "github.clone(repo) / github.gh('pr', 'create', '--fill')": "a real checkout and the gh cli",
    "browser.start() / goto(url) / click(sel) / shot()": "a real Chrome on the machine; shot() comes back as a picture",
    "ssh.run(cmd, host) / ssh.hosts()": "the user's own servers; the private key is already on the machine",
    "store.put/get/listing, kv['x'], secrets['NAME']": "state that outlives the machine",
    "ci.add(repo) / ci.status(repo)": "run the CI of a repository on the pool",
    "automation.schedule / watch / subscribe / timezone": "things that happen later or on their own",
    "fetch(url)": "a page as markdown, an api as json",
}


def help() -> None:  # noqa: A001
    """Print the map of the SDK: one line per thing it can do."""
    width = max(len(name) for name in MAP)
    for name, what in MAP.items():
        print(f"{name.ljust(width)}  {what}")


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
    "chrome",
    "ci",
    "client",
    "fan",
    "fetch",
    "file",
    "github",
    "help",
    "install",
    "kv",
    "machines",
    "me",
    "net",
    "note",
    "packages",
    "page",
    "pages",
    "photo",
    "progress",
    "quota",
    "release",
    "run",
    "say",
    "secrets",
    "setting",
    "setup",
    "ssh",
    "store",
    "submit",
    "take",
]
