import asyncio
import logging
import tarfile
import tempfile
import time
from pathlib import Path

from unsafie import cluster, telemetry
from unsafie.github import cache, metrics
from unsafie.github.client.repo import RepoClient
from unsafie.github.vfs import SKIP_DIRS
from unsafie.mime import human_size
from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)


def name_for(full: str, commit_sha: str) -> str:
    return f"snapshot:{full}:{commit_sha}"


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
                await _refuse(client.full, commit_sha)
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


async def _refuse(full: str, commit_sha: str) -> None:
    await cluster.mark(name_for(full, commit_sha), "refused", settings.snapshot_refused_ttl)


async def hydrate(client: RepoClient, commit_sha: str) -> int:
    name = name_for(client.full, commit_sha)
    if await cluster.marked(name):
        return 0
    async with cluster.try_lock(
        name, ttl=settings.snapshot_lock_ttl, wait=settings.snapshot_wait, renew=True,
    ) as held:
        if held is None:
            logger.info(
                "github snapshot %s@%s is taking too long elsewhere, reading blobs instead",
                client.full,
                commit_sha[:7],
            )
            return 0
        if await cluster.marked(name):
            return 0
        try:
            return await _snapshot(client, commit_sha)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("github snapshot %s@%s failed: %s", client.full, commit_sha[:7], e)
            await _refuse(client.full, commit_sha)
            return 0
