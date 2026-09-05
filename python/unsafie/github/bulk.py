"""One request instead of N: the whole repository at a commit, as a tarball.

Reading files through the blobs API costs a request per file. The same content is available as a
single archive, and the blob sha of every file can be computed locally — so one download fills
the content-addressed cache for the entire snapshot, and everything after it is a local read.

Anything the archive does not carry (export-ignore, LFS pointers, files over the limit) simply
stays missing and is fetched the usual way.
"""

import asyncio
import logging
import tarfile
import tempfile
import time
from pathlib import Path

from unsafie.github import cache, metrics
from unsafie.github.client.repo import RepoClient
from unsafie.github.vfs import SKIP_DIRS
from unsafie.mime import human_size
from unsafie.settings import settings

logger = logging.getLogger(__name__)

_inflight: dict[tuple[str, str], asyncio.Task] = {}
_refused: set[tuple[str, str]] = set()
REFUSED_LIMIT = 500


def _skipped(path: str) -> bool:
    return any(path.startswith(d) or f"/{d}" in path for d in SKIP_DIRS)


def _extract(archive: Path) -> tuple[int, int]:
    """Put every reasonable file of the archive into the blob cache. Runs in a worker thread.

    Nothing is written to the paths from the archive: members are read into memory and stored
    under their own sha, so a crafted archive cannot escape anywhere.
    """
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
    with tempfile.TemporaryDirectory(prefix="unsafie-snapshot-") as directory:
        archive = Path(directory) / "repo.tar.gz"
        size = await client.stream(
            f"{client.base}/tarball/{commit_sha}",
            archive,
            limit=settings.github_bulk_max_bytes,
        )
        if size is None:
            logger.info(
                "github snapshot %s is over %s, falling back to single blobs",
                client.full,
                human_size(settings.github_bulk_max_bytes),
            )
            _refuse((client.full, commit_sha))
            return 0
        files, total = await asyncio.to_thread(_extract, archive)
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
    """Fill the cache from one snapshot. Never fatal: on any trouble we just fetch blobs later."""
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
