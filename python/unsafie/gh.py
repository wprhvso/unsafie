import asyncio
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "2.100.0"
CACHE_DIR = Path.home() / ".local" / "share" / "unsafie" / "bin"
CACHED_BIN = CACHE_DIR / "gh"

CANDIDATES = (
    CACHED_BIN,
    Path.home() / ".local" / "bin" / "gh",
    Path("/usr/local/bin/gh"),
    Path("/usr/bin/gh"),
    Path("/opt/homebrew/bin/gh"),
)


def _find() -> str | None:
    found = shutil.which("gh")
    if found:
        return found
    for path in CANDIDATES:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    return "amd64"


def _url() -> str:
    arch = _arch()
    return f"https://github.com/cli/cli/releases/download/v{VERSION}/gh_{VERSION}_linux_{arch}.tar.gz"


def _install() -> str:
    url = _url()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "gh.tar.gz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("/bin/gh") or member.name == "gh":
                    f = tar.extractfile(member)
                    if f:
                        CACHED_BIN.write_bytes(f.read())
                        CACHED_BIN.chmod(0o755)
                        return str(CACHED_BIN)
    msg = "could not extract gh binary"
    raise RuntimeError(msg)


async def ensure_gh() -> str:
    found = _find()
    if found:
        return found
    return await asyncio.to_thread(_install)
