from unsafie_cli import spec
from unsafie_cli.errors import Usage
from unsafie_cli.output import Out
from unsafie_cli.spec import Cmd


def _status(cmd: Cmd) -> str:
    return "" if cmd.phase <= spec.READY_THROUGH else f"(phase {cmd.phase})"


def overview(out: Out) -> None:
    if out.json_mode:
        out.send(spec.index())
        return
    out.line("unsafie — everything the agent and the human can do, as commands")
    out.line()
    out.line(out.bold("usage"))
    out.line("  unsafie [--json] <command> [arguments] [flags]")
    out.line()
    out.line(out.bold("groups"))
    for name, summary in spec.GROUPS.items():
        if name == "internal":
            continue
        out.line(f"  {name.ljust(11)} {summary}")
    out.line()
    out.line(out.bold("start here"))
    for line in (
        "  unsafie auth login --token …    the bot gives you the token with /auth",
        "  unsafie help <group>            what a group can do",
        "  unsafie <command> --help        arguments, flags, examples",
        "  unsafie help --json             the whole index in one answer",
    ):
        out.line(line)
    out.line()
    out.line(out.dim("topics: " + ", ".join(spec.TOPICS)))


def group(out: Out, name: str) -> None:
    commands = spec.in_group(name)
    if out.json_mode:
        out.send(
            {
                "group": name,
                "summary": spec.GROUPS[name],
                "commands": [cmd.as_dict() for cmd in commands],
            }
        )
        return
    out.line(out.bold(name) + " — " + spec.GROUPS[name])
    out.line()
    for cmd in commands:
        mark = _status(cmd)
        tail = f" {out.dim(mark)}" if mark else ""
        out.line(f"  {cmd.name.ljust(22)} {cmd.summary}{tail}")


def command(out: Out, cmd: Cmd) -> None:
    if out.json_mode:
        out.send(cmd.as_dict())
        return
    out.line(out.bold(cmd.usage))
    out.line(f"  {cmd.summary}")
    if cmd.phase > spec.READY_THROUGH:
        out.line(out.dim(f"  not implemented yet — phase {cmd.phase}"))
    if cmd.args:
        out.line()
        out.line(out.bold("arguments"))
        for arg in cmd.args:
            out.line(f"  {arg.display}")
    if cmd.flags:
        out.line()
        out.line(out.bold("flags"))
        for flag in cmd.flags:
            note = flag.help or ""
            if flag.default:
                note = f"{note} (default {flag.default})".strip()
            out.line(f"  {flag.display.ljust(24)} {note}".rstrip())
    if cmd.examples:
        out.line()
        out.line(out.bold("examples"))
        for example in cmd.examples:
            out.line(f"  {example}")
    siblings = [c for c in spec.prefixed(cmd.path[:1]) if c.path != cmd.path and not c.internal]
    if siblings and len(cmd.path) > 1:
        out.line()
        out.line(out.dim("see also: " + ", ".join(sorted(c.name for c in siblings))))


def topic(out: Out, name: str) -> None:
    lines = spec.TOPICS[name]
    if out.json_mode:
        out.send({"topic": name, "text": "\n".join(lines)})
        return
    for index, line in enumerate(lines):
        out.line(out.bold(line) if index == 0 else line)


def render(out: Out, tokens: list[str]) -> int:
    if not tokens:
        overview(out)
        return 0
    if len(tokens) == 1 and tokens[0] in spec.TOPICS:
        topic(out, tokens[0])
        return 0
    if len(tokens) == 1 and tokens[0] in spec.GROUPS:
        group(out, tokens[0])
        return 0
    found = spec.match(tokens)
    if found is None:
        raise Usage(
            f"nothing known about '{' '.join(tokens)}'",
            "`unsafie help` lists the groups and the topics",
        )
    command(out, found[0])
    return 0
