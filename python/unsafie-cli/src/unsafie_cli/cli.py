import sys

from unsafie_cli import commands, parser
from unsafie_cli import help as help_pages
from unsafie_cli.errors import FAILED, OK, CliError
from unsafie_cli.output import Out, colors_wanted


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        help_pages.overview(Out(color=colors_wanted()))
        return OK
    if argv[0] in ("-V", "--version"):
        argv = ["version", *argv[1:]]
    call = parser.parse(argv)
    out = Out(call.options.json_mode, call.options.quiet, call.options.color and colors_wanted())
    if call.wants_help:
        help_pages.command(out, call.cmd)
        return OK
    return commands.lookup(call.cmd.path)(call, out)


def main() -> int:
    out = Out(json_mode="--json" in sys.argv, color=colors_wanted())
    try:
        return run(sys.argv[1:])
    except CliError as problem:
        out.problem(problem.message, problem.hint)
        return problem.code
    except KeyboardInterrupt:
        out.problem("interrupted")
        return 130
    except BrokenPipeError:
        return OK
    except Exception as unexpected:
        out.problem(f"{type(unexpected).__name__}: {unexpected}")
        return FAILED


if __name__ == "__main__":
    raise SystemExit(main())
