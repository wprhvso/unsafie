import asyncio
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "0.102.0"
CACHE_DIR = Path.home() / ".local" / "share" / "unsafie" / "bin"
CACHED_BIN = CACHE_DIR / "nu"

CANDIDATES = (
    CACHED_BIN,
    Path.home() / ".local" / "bin" / "nu",
    Path.home() / ".cargo" / "bin" / "nu",
    Path("/usr/local/bin/nu"),
    Path("/usr/bin/nu"),
    Path("/opt/homebrew/bin/nu"),
)


def _find() -> str | None:
    found = shutil.which("nu")
    if found:
        return found
    for path in CANDIDATES:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "aarch64"
    return "x86_64"


def _url() -> str:
    arch = _arch()
    if sys.platform == "darwin":
        return f"https://github.com/nushell/nushell/releases/download/{VERSION}/nu-{VERSION}-{arch}-apple-darwin.tar.gz"
    return f"https://github.com/nushell/nushell/releases/download/{VERSION}/nu-{VERSION}-{arch}-unknown-linux-musl.tar.gz"


def _install() -> str:
    url = _url()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "nu.tar.gz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("/nu") or member.name == "nu":
                    f = tar.extractfile(member)
                    if f:
                        CACHED_BIN.write_bytes(f.read())
                        CACHED_BIN.chmod(0o755)
                        return str(CACHED_BIN)
    raise RuntimeError("could not extract nu binary")


async def ensure_nu() -> str:
    found = _find()
    if found:
        return found
    return await asyncio.to_thread(_install)
