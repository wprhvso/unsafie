from collections.abc import Callable

from unsafie_cli.commands import auth, meta, settings
from unsafie_cli.errors import NotReady
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

Handler = Callable[[Call, Out], int]

HANDLERS: dict[tuple[str, ...], Handler] = {
    ("help",): meta.show_help,
    ("version",): meta.version,
    ("completion",): meta.completion,
    ("config", "show"): settings.show,
    ("config", "get"): settings.get,
    ("config", "set"): settings.put,
    ("config", "unset"): settings.unset,
    ("config", "path"): settings.where,
    ("auth", "login"): auth.login,
    ("auth", "status"): auth.status,
    ("auth", "logout"): auth.logout,
    ("auth", "token"): auth.token,
}


def pending(call: Call, out: Out) -> int:
    _ = out
    raise NotReady(call.cmd.name, call.cmd.phase)


def lookup(path: tuple[str, ...]) -> Handler:
    return HANDLERS.get(path, pending)
