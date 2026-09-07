from unsafie_cli import config
from unsafie_cli.errors import NoAuth, NotReady, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

MACHINE_HINT = "on a machine in the pool the token arrives in UNSAFIE_TOKEN and needs no login"


def login(call: Call, out: Out) -> int:
    if call.on("pair"):
        raise NotReady("auth login --pair", 2)
    token = call.flag("token") or call.options.token or ""
    if not token:
        raise Usage(
            "no token given",
            "ask the bot for one with /auth, then: unsafie auth login --token uns_…",
        )
    values = config.load()
    values["token"] = token
    api = call.flag("api") or call.options.api
    if api:
        values["api"] = api
    saved = config.save(values)
    out.send(
        {"saved": str(saved), "token": config.mask(token), "api": values.get("api", config.DEFAULT_API)},
        [f"token saved to {saved}", f"server: {values.get('api', config.DEFAULT_API)}"],
    )
    return 0


def status(call: Call, out: Out) -> int:
    token = config.resolve("token", call.options.token)
    api = config.resolve("api", call.options.api)
    chat = config.resolve("chat", call.options.chat)
    machine = config.resolve("machine", call.options.machine)
    payload = {
        "authorized": token is not None,
        "token": config.mask(token.value) if token else None,
        "token_source": token.source if token else None,
        "api": api.value if api else None,
        "chat": chat.value if chat else None,
        "machine": machine.value if machine else None,
        "config": str(config.path()),
    }
    rows = [
        ("token", payload["token"] or "—", payload["token_source"] or "not set"),
        ("api", api.value if api else "—", api.source if api else ""),
        ("chat", chat.value if chat else "—", chat.source if chat else ""),
        ("machine", machine.value if machine else "—", machine.source if machine else ""),
    ]
    if out.json_mode:
        out.send(payload)
        return 0
    out.table(rows, ("setting", "value", "from"))
    if token is None:
        out.line()
        out.line(out.dim("no token yet: /auth in Telegram, then unsafie auth login --token …"))
        out.line(out.dim(MACHINE_HINT))
    return 0


def logout(call: Call, out: Out) -> int:
    values = config.load()
    had = values.pop("token", None)
    saved = config.save(values)
    _ = call
    out.send({"forgotten": bool(had), "config": str(saved)}, ["token forgotten" if had else "no stored token"])
    return 0


def token(call: Call, out: Out) -> int:
    found = config.resolve("token", call.options.token)
    if found is None:
        raise NoAuth()
    shown = found.value if call.on("raw") else config.mask(found.value)
    out.send({"token": shown, "source": found.source}, [shown])
    return 0
