import contextlib
import json
import resource
import sys
import tempfile
from typing import Any

from unsafie.bloat2md.config import settings
from unsafie.bloat2md.domain import ConversionError, UnsupportedFile


def _restrict() -> None:
    limits = settings()
    memory = limits.memory_limit_mb * 1024 * 1024
    with contextlib.suppress(Exception):
        resource.setrlimit(resource.RLIMIT_DATA, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    output = limits.output_limit_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _emit(body: dict[str, Any]) -> None:
    _ = sys.stdout.write(json.dumps(body))
    sys.stdout.flush()


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.buffer.read()

    with tempfile.TemporaryDirectory(prefix="bloat2md-work-") as workdir:
        tempfile.tempdir = workdir
        _restrict()
        from unsafie.bloat2md.service import convert

        try:
            kind, payload = convert(raw, name)
        except UnsupportedFile as error:
            _emit({"error": "unsupported", "detail": str(error)})
            return 0
        except ConversionError as error:
            _emit({"error": "failed", "detail": str(error)})
            return 0
        except MemoryError:
            _emit({"error": "failed", "detail": "the document needed too much memory"})
            return 0

        _emit(
            {
                "kind": kind.value,
                "markdown": payload.markdown,
                "images": [
                    {"mime": image.mime, "data": image.data.hex()} for image in payload.images
                ],
                "pages": payload.pages,
                "truncated": payload.truncated,
                "dropped": payload.dropped,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
