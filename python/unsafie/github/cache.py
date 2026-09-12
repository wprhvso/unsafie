import asyncio
import contextlib
import hashlib
import json
from unsafie.log import get_logger
import os
import stat
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from unsafie.github import metrics
from unsafie.loop import Loop
from unsafie.mime import human_size
from unsafie.settings import settings

logger = get_logger(__name__)

TOUCH_AFTER = 86_400.0
SWEEP_TARGET = 0.8


def git_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _read(path: Path) -> bytes | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("github cache: cannot read %s: %s", path, e)
        return None
    try:
        now = time.time()
        if now - path.stat().st_mtime > TOUCH_AFTER:
            os.utime(path, (now, now))
    except OSError:
        pass
    return data


def _write(path: Path, data: bytes) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
            tmp.write(data)
        os.replace(temporary, path)
        temporary = None
    except OSError as e:
        logger.warning("github cache: cannot write %s: %s", path, e)
    finally:
        if temporary is not None and temporary.exists():
            with contextlib.suppress(OSError):
                temporary.unlink()


def _sweep(root: Path, cap: int) -> tuple[int, int]:
    files: list[tuple[float, int, Path]] = []
    total = 0
    for path in root.rglob("*"):
        try:
            info = path.stat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        files.append((info.st_mtime, info.st_size, path))
        total += info.st_size
    if total <= cap:
        return 0, total
    files.sort()
    target = total - int(cap * SWEEP_TARGET)
    freed = 0
    for _, size, path in files:
        if freed >= target:
            break
        try:
            path.unlink()
        except OSError:
            continue
        freed += size
    return freed, total


class Store:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._memory: OrderedDict[str, bytes] = OrderedDict()
        self._bytes = 0
        self._dir: Path | None = None
        self._resolved = False

    @property
    def directory(self) -> Path | None:
        if not self._resolved:
            self._resolved = True
            path = Path(settings.github_cache_dir) / self.kind
            try:
                path.mkdir(parents=True, exist_ok=True)
                self._dir = path
                logger.info("github cache: %s in %s", self.kind, path)
            except OSError as e:
                logger.warning("github cache: %s is not writable (%s), memory only", path, e)
        return self._dir

    def _path(self, key: str) -> Path | None:
        directory = self.directory
        return None if directory is None else directory / key[:2] / key

    def _remember(self, key: str, data: bytes) -> None:
        if len(data) > settings.github_cache_item_bytes:
            return
        if key in self._memory:
            self._memory.move_to_end(key)
            return
        self._memory[key] = data
        self._bytes += len(data)
        while self._bytes > settings.github_cache_memory_bytes and len(self._memory) > 1:
            _, evicted = self._memory.popitem(last=False)
            self._bytes -= len(evicted)

    def cached(self, key: str) -> bool:
        if key in self._memory:
            return True
        path = self._path(key)
        return bool(path is not None and path.exists())

    def missing(self, keys) -> list[str]:
        return [key for key in dict.fromkeys(keys) if key and not self.cached(key)]

    async def get(self, key: str) -> bytes | None:
        data = self._memory.get(key)
        if data is None:
            path = self._path(key)
            if path is None:
                return None
            data = await asyncio.to_thread(_read, path)
            if data is None:
                return None
            self._remember(key, data)
        else:
            self._memory.move_to_end(key)
        metrics.bump("hits")
        return data

    async def put(self, key: str, data: bytes) -> None:
        self._remember(key, data)
        path = self._path(key)
        if path is not None:
            await asyncio.to_thread(_write, path, data)

    def store(self, key: str, data: bytes) -> None:
        path = self._path(key)
        if path is not None:
            _write(path, data)

    async def get_json(self, key: str) -> Any | None:
        data = await self.get(key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except ValueError:
            return None

    async def put_json(self, key: str, value: Any) -> None:
        await self.put(key, json.dumps(value).encode())

    def state(self) -> dict:
        return {
            "kind": self.kind,
            "memory_items": len(self._memory),
            "memory_bytes": self._bytes,
            "directory": str(self.directory or ""),
        }


blobs = Store("blobs")
trees = Store("trees")


class Sweeper(Loop):
    name = "github-cache"
    interval = float(settings.github_cache_sweep_interval)
    startup_delay = 30.0

    async def tick(self) -> None:
        root = Path(settings.github_cache_dir)
        if not root.is_dir():
            return
        freed, total = await asyncio.to_thread(_sweep, root, settings.github_cache_disk_bytes)
        if freed:
            logger.info(
                "github cache swept: %s freed of %s", human_size(freed), human_size(total),
            )


sweeper = Sweeper()
