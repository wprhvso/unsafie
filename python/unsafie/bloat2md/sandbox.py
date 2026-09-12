import asyncio
import contextlib
import json
from unsafie.log import get_logger
import os
import signal
import sys
from typing import Any, Final

from unsafie.bloat2md.config import settings
from unsafie.bloat2md.domain import ConversionError, Image, Payload, UnsupportedFile

logger = get_logger(__name__)

WORKER: Final = "unsafie.bloat2md.worker"
_KILL_GRACE: Final = 2.0


class SandboxTimeout(ConversionError):
    pass


def _payload(body: dict[str, Any]) -> Payload:
    return Payload(
        markdown=str(body.get("markdown", "")),
        images=[
            Image(mime=str(item["mime"]), data=bytes.fromhex(str(item["data"])))
            for item in body.get("images", [])
        ],
        pages=int(body.get("pages", 0)),
        truncated=bool(body.get("truncated", False)),
        dropped={str(key): int(value) for key, value in body.get("dropped", {}).items()},
    )


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(_KILL_GRACE):
            _ = await process.wait()


async def run_isolated(raw: bytes, name: str, max_pages: int | None = None) -> tuple[str, Payload]:
    limits = settings()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        WORKER,
        name,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "PYTHONPATH": os.pathsep.join(sys.path),
            "BLOAT2MD_MEMORY_LIMIT_MB": str(limits.memory_limit_mb),
            "BLOAT2MD_CPU_SECONDS": str(limits.cpu_seconds),
            "BLOAT2MD_OUTPUT_LIMIT_MB": str(limits.output_limit_mb),
            "BLOAT2MD_MAX_PAGES": str(max_pages if max_pages is not None else limits.max_pages),
            "BLOAT2MD_MAX_RENDER_PAGES": str(limits.max_render_pages),
            "BLOAT2MD_RENDER_EDGE": str(limits.render_edge),
            "BLOAT2MD_RENDER_QUALITY": str(limits.render_quality),
            "BLOAT2MD_MAX_MARKDOWN_CHARS": str(limits.max_markdown_chars),
            "BLOAT2MD_MAX_IMAGE_PIXELS": str(limits.max_image_pixels),
            "BLOAT2MD_LIBREOFFICE": str(limits.libreoffice),
        },
    )

    try:
        async with asyncio.timeout(limits.timeout):
            out, err = await process.communicate(raw)
    except TimeoutError as error:
        await _terminate(process)
        msg = "the document took too long to convert"
        raise SandboxTimeout(msg) from error
    finally:
        await _terminate(process)

    if process.returncode != 0 or not out:
        logger.info(
            "conversion_worker_failed code=%s stderr=%s",
            process.returncode,
            err[-512:].decode("utf-8", "replace"),
        )
        msg = "the document could not be converted"
        raise ConversionError(msg)

    try:
        body = json.loads(out)
    except ValueError as error:
        msg = "the converter returned nothing usable"
        raise ConversionError(msg) from error

    if not isinstance(body, dict):
        msg = "the converter returned nothing usable"
        raise ConversionError(msg)
    if body.get("error") == "unsupported":
        raise UnsupportedFile(str(body.get("detail", "unsupported file")))
    if "error" in body:
        raise ConversionError(str(body.get("detail", "conversion failed")))
    return str(body.get("kind", "")), _payload(body)
