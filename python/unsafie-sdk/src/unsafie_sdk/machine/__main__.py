import os
import sys
from pathlib import Path

from unsafie_sdk.client import DEFAULT_API, setting
from unsafie_sdk.machine.daemon import serve

USAGE = """unsafie-machine — what a pool machine runs for itself

  unsafie-machine serve                         become a machine of the pool
  unsafie-machine put <key> <file>              store a file under a key
  unsafie-machine get <key> <file>              write a stored file here
  unsafie-machine ci-runner --jit <config>      become a github runner for one job
"""


def _flag(argv: list[str], name: str, fallback: str = "") -> str:
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    for item in argv:
        if item.startswith(f"{name}="):
            return item.split("=", 1)[1]
    return fallback


def main() -> int:
    argv = sys.argv[1:]
    action = argv[0] if argv and not argv[0].startswith("-") else "serve"
    if action in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0
    if action == "serve":
        token = _flag(argv, "--token") or os.environ.get("UNSAFIE_WORKER_TOKEN") or ""
        if not token:
            sys.stderr.write("no worker token: set UNSAFIE_WORKER_TOKEN\n")
            return 2
        api = _flag(argv, "--api") or setting("api") or DEFAULT_API
        return serve(api, token)
    if action in ("put", "get"):
        from unsafie_sdk import store

        if len(argv) < 3:
            sys.stderr.write(USAGE)
            return 2
        key, path = argv[1], Path(argv[2])
        if action == "put":
            store.put(key, path)
        else:
            store.download(key, path)
        return 0
    if action == "ci-runner":
        from unsafie_sdk.machine.runner import run_runner

        return run_runner(
            _flag(argv, "--jit"),
            name=_flag(argv, "--name"),
            repo=_flag(argv, "--repo"),
            idle=float(_flag(argv, "--idle", "300")),
            lifetime=float(_flag(argv, "--lifetime", "3600")),
        )
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
