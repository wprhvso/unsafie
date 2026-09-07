from collections.abc import Callable

from unsafie_cli.commands import account, auth, chat, meta, pages, pool, settings, store
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
    ("me",): account.me,
    ("say",): chat.say,
    ("file",): chat.file,
    ("edit",): chat.edit,
    ("rm",): chat.remove,
    ("note",): chat.note,
    ("progress",): chat.progress,
    ("typing",): chat.typing,
    ("page", "create"): pages.create,
    ("page", "list"): pages.listing,
    ("page", "update"): pages.update,
    ("page", "rm"): pages.remove,
    ("machines",): pool.machines,
    ("take",): pool.take,
    ("release",): pool.release,
    ("rename",): pool.rename,
    ("run",): pool.run,
    ("fan",): pool.fan,
    ("job", "submit"): pool.submit,
    ("job", "list"): pool.jobs,
    ("job", "logs"): pool.logs,
    ("job", "cancel"): pool.cancel,
    ("serve",): pool.serve,
    ("blob", "put"): store.blob_put,
    ("blob", "get"): store.blob_get,
    ("blob", "ls"): store.blob_ls,
    ("blob", "rm"): store.blob_rm,
    ("blob", "url"): store.blob_url,
    ("kv", "set"): store.kv_set,
    ("kv", "get"): store.kv_get,
    ("kv", "ls"): store.kv_ls,
    ("kv", "rm"): store.kv_rm,
    ("secret", "set"): store.secret_set,
    ("secret", "get"): store.secret_get,
    ("secret", "ls"): store.secret_ls,
    ("secret", "rm"): store.secret_rm,
    ("secret", "env"): store.secret_env,
}


def pending(call: Call, out: Out) -> int:
    _ = out
    raise NotReady(call.cmd.name, call.cmd.phase)


def lookup(path: tuple[str, ...]) -> Handler:
    return HANDLERS.get(path, pending)
