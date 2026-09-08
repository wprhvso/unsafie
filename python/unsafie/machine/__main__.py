import os
import sys
from pathlib import Path


def _flag(argv: list[str], name: str, fallback: str = "") -> str:
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    for item in argv:
        if item.startswith(f"{name}="):
            return item.split("=", 1)[1]
    return fallback


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args and not args[0].startswith("-") else "serve"
    if action in ("-h", "--help", "help"):
        sys.stdout.write("unsafie-machine [setup|serve|ci-runner|put|get]\n")
        return 0
    if action == "setup":
        from unsafie.machine.toolchains import TOOLCHAINS, setup
        wanted = [name for name in args[1:] if not name.startswith("-")] or list(TOOLCHAINS)
        for name, outcome in setup(*wanted).items():
            sys.stdout.write(f"{name}: {outcome}\n")
        return 0
    if action == "serve":
        token = _flag(args, "--token") or os.environ.get("UNSAFIE_WORKER_TOKEN") or ""
        api = _flag(args, "--api") or os.environ.get("UNSAFIE_API") or "http://127.0.0.1:8000"
        if not token:
            sys.stderr.write("no worker token: set UNSAFIE_WORKER_TOKEN\n")
            return 0
        from unsafie.machine.daemon import serve
        return serve(api, token)
    if action in ("put", "get"):
        from unsafie.cli import blobs
        if len(args) < 3:
            return 2
        key, path = args[1], Path(args[2])
        if action == "put":
            blobs.put(key, path)
        else:
            target = Path(path)
            target.write_bytes(blobs.get(key))
        return 0
    if action == "ci-runner":
        from unsafie.machine.runner import run_runner
        return run_runner(
            _flag(args, "--jit"),
            name=_flag(args, "--name"),
            repo=_flag(args, "--repo"),
            idle=float(_flag(args, "--idle", "300")),
            lifetime=float(_flag(args, "--lifetime", "3600")),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
