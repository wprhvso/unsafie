import importlib
import shutil
import site
import subprocess
import sys
import sysconfig

from unsafie_sdk.errors import UnsafieError


def install(*packages: str, upgrade: bool = False, timeout: float = 600.0) -> list[str]:
    """Install python packages into this interpreter with uv, right now.

    install("pandas", "httpx") — then simply `import pandas`.
    """
    wanted = [name for name in packages if name.strip()]
    if not wanted:
        return []
    line = _installer(wanted, upgrade)
    done = subprocess.run(line, capture_output=True, text=True, check=False, timeout=timeout)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip()[-600:]
        raise UnsafieError(f"could not install {', '.join(wanted)}: {tail}")
    _refresh()
    return wanted


def _installer(packages: list[str], upgrade: bool) -> list[str]:
    if shutil.which("uv"):
        line = ["uv", "pip", "install", "--python", sys.executable, "--quiet"]
    else:
        line = [sys.executable, "-m", "pip", "install", "--quiet"]
    if upgrade:
        line.append("--upgrade")
    return [*line, *packages]


def _refresh() -> None:
    for path in {sysconfig.get_paths().get("purelib"), *site.getsitepackages()}:
        if path and path not in sys.path:
            sys.path.append(path)
    importlib.invalidate_caches()
