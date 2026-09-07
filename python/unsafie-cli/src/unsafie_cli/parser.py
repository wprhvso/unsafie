from dataclasses import dataclass, field
from typing import Any

from unsafie_cli import spec
from unsafie_cli.errors import Usage
from unsafie_cli.spec import Cmd, Flag

GLOBAL_NAMES = frozenset({"json", "quiet", "no-color", "api", "token", "chat", "machine"})


@dataclass(slots=True)
class Options:
    json_mode: bool = False
    quiet: bool = False
    color: bool = True
    api: str | None = None
    token: str | None = None
    chat: str | None = None
    machine: str | None = None


@dataclass(slots=True)
class Call:
    cmd: Cmd
    options: Options
    args: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    rest: list[str] = field(default_factory=list)
    wants_help: bool = False

    def arg(self, name: str, fallback: str = "") -> str:
        value = self.args.get(name)
        if isinstance(value, list):
            return value[0] if value else fallback
        return str(value) if value else fallback

    def many(self, name: str) -> list[str]:
        value = self.args.get(name)
        if not value:
            return []
        return list(value) if isinstance(value, list) else [str(value)]

    def flag(self, name: str, fallback: str = "") -> str:
        value = self.flags.get(name)
        if value is None or isinstance(value, bool):
            return fallback
        return str(value)

    def on(self, name: str) -> bool:
        return bool(self.flags.get(name))


def _known(cmd: Cmd | None) -> dict[str, Flag]:
    table: dict[str, Flag] = {}
    for flag in (*spec.GLOBAL_FLAGS, *(cmd.flags if cmd else ())):
        table[flag.long] = flag
        if flag.short:
            table[flag.short] = flag
    return table


def _apply_global(options: Options, name: str, value: str | bool) -> None:
    match name:
        case "json":
            options.json_mode = True
        case "quiet":
            options.quiet = True
        case "no-color":
            options.color = False
        case "api" | "token" | "chat" | "machine":
            setattr(options, name, str(value))


def _defaults(cmd: Cmd) -> dict[str, Any]:
    return {flag.long: flag.default for flag in cmd.flags if flag.default}


def _take_command(tokens: list[str]) -> tuple[Cmd, list[str]]:
    head: list[str] = []
    for token in tokens[:3]:
        if token.startswith("-"):
            break
        head.append(token)
    found = spec.match(head)
    if found is None:
        name = head[0] if head else ""
        raise Usage(
            f"unknown command '{name}'" if name else "no command given",
            "`unsafie help` lists the groups, `unsafie help --json` lists everything",
        )
    cmd, _ = found
    return cmd, tokens[len(cmd.path) :]


def _bind(cmd: Cmd, values: list[str]) -> dict[str, Any]:
    bound: dict[str, Any] = {}
    left = list(values)
    for arg in cmd.args:
        if arg.repeat:
            bound[arg.name] = left
            left = []
        elif left:
            bound[arg.name] = left.pop(0)
        elif arg.optional:
            bound[arg.name] = ""
        else:
            raise Usage(f"missing <{arg.name}>", cmd.usage)
    if left and not cmd.passthrough:
        raise Usage(f"too many arguments: {' '.join(left)}", cmd.usage)
    return bound


def parse(argv: list[str]) -> Call:
    tokens = list(argv)
    leading: list[str] = []
    while tokens and tokens[0].startswith("-"):
        flag_token = tokens.pop(0)
        leading.append(flag_token)
        name = flag_token.lstrip("-").partition("=")[0]
        wanted = _known(None).get(name)
        if wanted is not None and wanted.takes_value and "=" not in flag_token and tokens:
            leading.append(tokens.pop(0))

    cmd, tail = _take_command(tokens)
    known = _known(cmd)
    call = Call(cmd, Options(), flags=_defaults(cmd))
    declared = {flag.long for flag in cmd.flags}

    stream = leading + tail
    positional: list[str] = []
    index = 0
    while index < len(stream):
        token = stream[index]
        index += 1
        if token == "--":
            call.rest = stream[index:]
            break
        if not token.startswith("-") or token == "-":
            positional.append(token)
            continue
        name, _, inline = token.lstrip("-").partition("=")
        flag = known.get(name)
        if flag is None:
            raise Usage(f"unknown flag '{token}'", f"see `unsafie help {cmd.name}`")
        value: str | bool = True
        if flag.takes_value:
            if inline:
                value = inline
            elif index < len(stream) and not stream[index].startswith("-"):
                value = stream[index]
                index += 1
            else:
                raise Usage(f"'--{flag.long}' needs a value", f"see `unsafie help {cmd.name}`")
        if flag.long == "help":
            call.wants_help = True
            continue
        if flag.long in GLOBAL_NAMES:
            _apply_global(call.options, flag.long, value)
            if flag.long not in declared:
                continue
        call.flags[flag.long] = value

    call.args = _bind(cmd, positional)
    return call
