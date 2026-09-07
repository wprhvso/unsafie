from unsafie_cli import config
from unsafie_cli.errors import NOT_FOUND, CliError
from unsafie_cli.output import Out
from unsafie_cli.parser import Call


def show(call: Call, out: Out) -> int:
    _ = call
    payload: dict[str, dict[str, str] | None] = {}
    rows: list[tuple[str, str, str]] = []
    for key in config.KEYS:
        found = config.resolve(key)
        if found is None:
            payload[key] = None
            rows.append((key, "—", "not set"))
            continue
        value = config.mask(found.value) if key == "token" else found.value
        payload[key] = {"value": value, "source": found.source}
        rows.append((key, value, found.source))
    if out.json_mode:
        out.send(payload)
        return 0
    out.table(rows, ("setting", "value", "from"))
    out.line()
    out.line(out.dim(f"file: {config.path()}"))
    return 0


def get(call: Call, out: Out) -> int:
    key = config.check(call.arg("key"))
    found = config.resolve(key)
    if found is None:
        raise CliError(f"'{key}' is not set", NOT_FOUND, f"unsafie config set {key} …")
    out.send({key: found.value, "source": found.source}, [found.value])
    return 0


def put(call: Call, out: Out) -> int:
    key = config.check(call.arg("key"))
    values = config.load()
    values[key] = call.arg("value")
    saved = config.save(values)
    out.send({key: values[key], "config": str(saved)}, [f"{key} = {values[key]}"])
    return 0


def unset(call: Call, out: Out) -> int:
    key = config.check(call.arg("key"))
    values = config.load()
    had = values.pop(key, None)
    saved = config.save(values)
    out.send(
        {"forgotten": had is not None, "config": str(saved)},
        [f"{key} forgotten" if had is not None else f"{key} was not set"],
    )
    return 0


def where(call: Call, out: Out) -> int:
    _ = call
    out.send({"config": str(config.path())}, [str(config.path())])
    return 0
