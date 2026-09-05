import base64
import fnmatch
import logging
import posixpath
from dataclasses import dataclass
from typing import Any

from unsafie.github.errors import GithubError
from unsafie.mime import human_size, is_text
from unsafie.settings import settings

logger = logging.getLogger(__name__)

DELETED = None
SKIP_DIRS = (".git/", "node_modules/", ".venv/", "__pycache__/", "dist/", "build/", "target/")


class TooLarge(GithubError):
    pass


def normalize(path: str) -> str:
    path = (path or "").strip().replace("\\", "/").lstrip("/")
    path = posixpath.normpath(path)
    if path in (".", "") or path.startswith("../"):
        raise GithubError(f"bad path: {path!r}")
    return path


def match(path: str, pattern: str) -> bool:
    pattern = pattern.strip().lstrip("/")
    if not pattern or pattern == "**":
        return True
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if "/" not in pattern and fnmatch.fnmatchcase(posixpath.basename(path), pattern):
        return True
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "**" in pattern:
        head, _, tail = pattern.partition("**")
        if path.startswith(head.rstrip("/")) and fnmatch.fnmatchcase(path, f"*{tail.lstrip('/')}"):
            return True
    return False


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode()


def decode(value: str) -> bytes:
    return base64.b64decode(value)


@dataclass
class Entry:
    path: str
    content: str | None
    mode: str = "100644"

    @property
    def deleted(self) -> bool:
        return self.content is None

    @property
    def data(self) -> bytes:
        return b"" if self.content is None else decode(self.content)


class Overlay:
    """Pending changes on top of a base tree: path -> base64 content or None for a deletion."""

    def __init__(self, changes: dict[str, Any] | None = None) -> None:
        self.changes: dict[str, Any] = dict(changes or {})

    def to_json(self) -> dict:
        return self.changes

    def __len__(self) -> int:
        return len(self.changes)

    def __contains__(self, path: str) -> bool:
        return path in self.changes

    @property
    def paths(self) -> list[str]:
        return sorted(self.changes)

    def entry(self, path: str) -> Entry | None:
        if path not in self.changes:
            return None
        item = self.changes[path]
        if item is None:
            return Entry(path, None)
        if isinstance(item, str):
            return Entry(path, item)
        return Entry(path, item.get("content"), item.get("mode", "100644"))

    def write(self, path: str, data: bytes, mode: str = "100644") -> None:
        if len(data) > settings.github_max_file_bytes:
            raise TooLarge(
                f"{path} is {human_size(len(data))}, limit is {human_size(settings.github_max_file_bytes)}"
            )
        self.changes[path] = {"content": encode(data), "mode": mode}
        self._check_size()

    def delete(self, path: str) -> None:
        self.changes[path] = None
        self._check_size()

    def forget(self, path: str) -> bool:
        return self.changes.pop(path, "missing") != "missing"

    def clear(self) -> None:
        self.changes.clear()

    def _check_size(self) -> None:
        if len(self.changes) > settings.github_max_changes:
            raise TooLarge(
                f"more than {settings.github_max_changes} changed files in one worktree; "
                "commit what is done (git_commit) before continuing"
            )

    def summary(self) -> list[str]:
        out = []
        for path in self.paths:
            entry = self.entry(path)
            if entry is None:
                continue
            if entry.deleted:
                out.append(f"D {path}")
            else:
                data = entry.data
                kind = "" if is_text(data) else " (binary)"
                out.append(f"M {path} ({human_size(len(data))}){kind}")
        return out


class Tree:
    """Flat view of a git tree with the overlay applied."""

    def __init__(self, entries: list[dict], overlay: Overlay) -> None:
        self.base = {e["path"]: e for e in entries if e.get("type") == "blob"}
        self.dirs = {e["path"] for e in entries if e.get("type") == "tree"}
        self.overlay = overlay

    def exists(self, path: str) -> bool:
        entry = self.overlay.entry(path)
        if entry is not None:
            return not entry.deleted
        return path in self.base

    def is_dir(self, path: str) -> bool:
        return path in self.dirs or any(p.startswith(path + "/") for p in self.paths())

    def blob_sha(self, path: str) -> str | None:
        item = self.base.get(path)
        return item.get("sha") if item else None

    def size(self, path: str) -> int | None:
        entry = self.overlay.entry(path)
        if entry is not None:
            return None if entry.deleted else len(entry.data)
        item = self.base.get(path)
        return item.get("size") if item else None

    def paths(self, pattern: str | None = None, include_skipped: bool = False) -> list[str]:
        names = set(self.base)
        for path in self.overlay.paths:
            entry = self.overlay.entry(path)
            if entry is None:
                continue
            if entry.deleted:
                names.discard(path)
            else:
                names.add(path)
        result = sorted(names)
        if not include_skipped:
            result = [
                p for p in result if not any(p.startswith(d) or f"/{d}" in p for d in SKIP_DIRS)
            ]
        if pattern:
            result = [p for p in result if match(p, pattern)]
        return result

    def listing(self, prefix: str) -> tuple[list[str], list[str]]:
        prefix = "" if prefix in ("", ".", "/") else normalize(prefix) + "/"
        files, dirs = [], set()
        for path in self.paths():
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix) :]
            if "/" in rest:
                dirs.add(rest.split("/", 1)[0] + "/")
            else:
                files.append(rest)
        return sorted(dirs), sorted(files)
