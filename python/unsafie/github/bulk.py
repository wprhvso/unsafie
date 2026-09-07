import asyncio
import logging
import tarfile
import tempfile
import time
from pathlib import Path

from unsafie import telemetry
from unsafie.github import cache, metrics
from unsafie.github.client.repo import RepoClient
from unsafie.github.vfs import SKIP_DIRS
from unsafie.mime import human_size
from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

_inflight: dict[tuple[str, str], asyncio.Task] = {}
_refused: set[tuple[str, str]] = set()
REFUSED_LIMIT = 500


def _skipped(path: str) -> bool:
    return any(path.startswith(d) or f"/{d}" in path for d in SKIP_DIRS)


def _extract(archive: Path) -> tuple[int, int]:
    files = 0
    total = 0
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or member.size > settings.github_bulk_file_bytes:
                continue
            _, _, name = member.name.partition("/")
            if not name or _skipped(name):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            cache.blobs.store(cache.git_sha(data), data)
            files += 1
            total += len(data)
            if total > settings.github_bulk_extract_bytes:
                logger.warning("github snapshot is over %s, stopping early", human_size(total))
                break
    return files, total


async def _snapshot(client: RepoClient, commit_sha: str) -> int:
    started = time.perf_counter()
    with telemetry.span(
        "github.snapshot",
        attributes={attrs.GH_REPO: client.full, attrs.GH_SHA: commit_sha[:7]},
    ) as span:
        with tempfile.TemporaryDirectory(prefix="unsafie-snapshot-") as directory:
            archive = Path(directory) / "repo.tar.gz"
            size = await client.stream(
                f"{client.base}/tarball/{commit_sha}",
                archive,
                limit=settings.github_bulk_max_bytes,
            )
            if size is None:
                telemetry.refused(span, "archive over the size limit")
                logger.info(
                    "github snapshot %s is over %s, falling back to single blobs",
                    client.full,
                    human_size(settings.github_bulk_max_bytes),
                )
                _refuse((client.full, commit_sha))
                return 0
            files, total = await asyncio.to_thread(_extract, archive)
        telemetry.set_attrs(span, {attrs.GH_FILES: files, attrs.GH_BYTES: total})
    metrics.bump("bulk", files)
    logger.info(
        "github snapshot %s@%s: %s file(s), %s from a %s archive in %.1fs",
        client.full,
        commit_sha[:7],
        files,
        human_size(total),
        human_size(size),
        time.perf_counter() - started,
    )
    return files


def _refuse(key: tuple[str, str]) -> None:
    if len(_refused) > REFUSED_LIMIT:
        _refused.clear()
    _refused.add(key)


async def hydrate(client: RepoClient, commit_sha: str) -> int:
    key = (client.full, commit_sha)
    if key in _refused:
        return 0
    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(_snapshot(client, commit_sha), name="github-snapshot")
        _inflight[key] = task
        task.add_done_callback(lambda _: _inflight.pop(key, None))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("github snapshot %s@%s failed: %s", client.full, commit_sha[:7], e)
        _refuse(key)
        return 0
