import platform
import sys
from importlib import metadata

from unsafie_cli import help as help_pages
from unsafie_cli import spec
from unsafie_cli.errors import Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

FALLBACK_VERSION = "0.1.0"


def version_of(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return FALLBACK_VERSION


def show_help(call: Call, out: Out) -> int:
    return help_pages.render(out, call.many("topic"))


def version(call: Call, out: Out) -> int:
    payload = {
        "cli": version_of("unsafie-cli"),
        "wire": version_of("unsafie-wire"),
        "python": platform.python_version(),
        "platform": f"{platform.system().lower()}-{platform.machine()}",
    }
    _ = call
    out.send(payload, [f"unsafie {payload['cli']} (wire {payload['wire']}, python {payload['python']})"])
    return 0


def _tree() -> dict[str, list[str]]:
    tree: dict[str, list[str]] = {}
    for cmd in spec.COMMANDS:
        head = cmd.path[0]
        tree.setdefault(head, [])
        if len(cmd.path) > 1 and cmd.path[1] not in tree[head]:
            tree[head].append(cmd.path[1])
    return tree


def _bash(tree: dict[str, list[str]]) -> str:
    cases = "\n".join(
        f"    {head}) COMPREPLY=($(compgen -W \"{' '.join(subs)}\" -- \"$cur\")) ;;"
        for head, subs in sorted(tree.items())
        if subs
    )
    tops = " ".join(sorted(tree))
    return f"""_unsafie() {{
  local cur prev
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  if [ "$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=($(compgen -W "{tops}" -- "$cur"))
    return
  fi
  case "$prev" in
{cases}
    *) COMPREPLY=() ;;
  esac
}}
complete -F _unsafie unsafie
"""


def _zsh(tree: dict[str, list[str]]) -> str:
    cases = "\n".join(
        f"      {head}) compadd {' '.join(subs)} ;;" for head, subs in sorted(tree.items()) if subs
    )
    tops = " ".join(sorted(tree))
    return f"""#compdef unsafie
_unsafie() {{
  if (( CURRENT == 2 )); then
    compadd {tops}
  else
    case "${{words[2]}}" in
{cases}
    esac
  fi
}}
compdef _unsafie unsafie
"""


def _fish(tree: dict[str, list[str]]) -> str:
    lines = [
        f"complete -c unsafie -n __fish_use_subcommand -a {head}" for head in sorted(tree)
    ]
    lines += [
        f'complete -c unsafie -n "__fish_seen_subcommand_from {head}" -a "{" ".join(subs)}"'
        for head, subs in sorted(tree.items())
        if subs
    ]
    return "\n".join(lines) + "\n"


def completion(call: Call, out: Out) -> int:
    shell = call.arg("shell").lower()
    tree = _tree()
    writers = {"bash": _bash, "zsh": _zsh, "fish": _fish}
    if shell not in writers:
        raise Usage(f"no completion for '{shell}'", "supported shells: bash, zsh, fish")
    sys.stdout.write(writers[shell](tree))
    _ = out
    return 0
