import os
import platform
import shutil
import time

from unsafie_cli import api, config
from unsafie_cli.errors import OK
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

TOOLS = (
    "git",
    "gh",
    "rg",
    "fd",
    "jq",
    "curl",
    "uv",
    "python3",
    "node",
    "go",
    "cargo",
    "docker",
    "google-chrome",
    "Xvfb",
)


def me(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/me")
    if out.json_mode:
        out.send(answer)
        return OK
    token = answer.get("token", {})
    out.table(
        [
            ("user", str(answer.get("user_id"))),
            ("chat", str(answer.get("chat_id") or "—")),
            ("machine", str(answer.get("machine") or "—")),
            ("token", f"{token.get('name')} ({token.get('kind')})"),
            ("scopes", ", ".join(token.get("scopes", []))),
        ]
    )
    return OK


def quota(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/pool/quota")
    if out.json_mode:
        out.send(answer)
        return OK
    limits = answer.get("limits", {})
    used = answer.get("used_today", {})
    capacity = answer.get("capacity", {})
    out.table(
        [
            ("machines", f"{answer.get('held', 0)} of {limits.get('machines')}"),
            ("background", str(limits.get("background"))),
            ("minutes today", f"{used.get('machine_minutes', 0)} of {limits.get('minutes_day')}"),
            ("commands today", str(used.get("commands", 0))),
            ("pool", f"{capacity.get('idle', 0)} idle of {capacity.get('total', 0)}"),
            ("blocked", "yes" if limits.get("blocked") else "no"),
        ]
    )
    return OK


def doctor(call: Call, out: Out) -> int:
    found = {name: shutil.which(name) for name in TOOLS}
    started = time.monotonic()
    reachable: object = False
    try:
        answer = api.client(call).call("GET", "/me")
        reachable = round((time.monotonic() - started) * 1000)
        who = f"user {answer.get('user_id')}"
    except Exception as broken:
        who = f"{type(broken).__name__}: {broken}"
    base = config.resolve("api")
    report = {
        "api": base.value if base else "-",
        "latency_ms": reachable,
        "identity": who,
        "machine": os.environ.get("UNSAFIE_MACHINE") or "-",
        "chat": os.environ.get("UNSAFIE_CHAT") or "-",
        "root": os.geteuid() == 0 if hasattr(os, "geteuid") else False,
        "platform": platform.platform(),
        "cpus": os.cpu_count(),
        "tools": {name: bool(path) for name, path in found.items()},
    }
    if out.json_mode:
        out.send(report)
        return OK
    out.table(
        [
            ("api", str(report["api"])),
            ("latency", f"{reachable} ms" if reachable else "unreachable"),
            ("identity", str(who)),
            ("machine", str(report["machine"])),
            ("root", "yes" if report["root"] else "no"),
            ("cpus", str(report["cpus"])),
        ]
    )
    missing = [name for name, path in found.items() if not path]
    out.line("")
    out.line("installed: " + " ".join(name for name, path in found.items() if path))
    if missing:
        out.line(out.dim("missing:   " + " ".join(missing)))
    return OK
