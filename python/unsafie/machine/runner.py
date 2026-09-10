import contextlib
import os
import platform
import shutil
import signal
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

OK = 0
FAILED = 1
RELEASES = "https://github.com/actions/runner/releases/latest"
DOWNLOAD = (
    "https://github.com/actions/runner/releases/download/v{version}/"
    "actions-runner-linux-{arch}-{version}.tar.gz"
)
ARCHES = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
KEEP = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LC_ALL", "TZ")
TOOLS = "/opt/hostedtoolcache"
LISTENER = "bin/Runner.Listener"
CACHE = Path(os.environ.get("UNSAFIE_RUNNER_CACHE") or "/opt/unsafie/runner")
SMALL = 1 << 20


def _arch() -> str:
    machine = platform.machine().lower()
    if machine not in ARCHES:
        msg = f"there is no actions runner for {machine}"
        raise RuntimeError(msg)
    return ARCHES[machine]


def _version() -> str:
    request = urllib.request.Request(RELEASES, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as answer:
        landed = answer.url
    tag = landed.rsplit("/v", 1)[-1].strip("/") if "/tag/v" in landed else ""
    if not tag:
        msg = f"could not tell the runner version from {landed}"
        raise RuntimeError(msg)
    return tag


def _tarball(version: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"actions-runner-linux-{_arch()}-{version}.tar.gz"
    if target.exists() and target.stat().st_size >= SMALL:
        return target
    part = target.with_suffix(".part")
    url = DOWNLOAD.format(version=version, arch=_arch())
    with urllib.request.urlopen(url, timeout=300) as answer, part.open("wb") as out:
        shutil.copyfileobj(answer, out, 1 << 20)
    part.replace(target)
    return target


def _unpack(archive: Path, root: Path) -> Path:
    with tarfile.open(archive) as tar:
        tar.extractall(root, filter="data")
    listener = root / LISTENER
    listener.chmod(0o755)
    return listener


def _environment(jit: str, root: Path) -> dict[str, str]:
    clean = {name: os.environ[name] for name in KEEP if os.environ.get(name)}
    clean["ACTIONS_RUNNER_INPUT_JITCONFIG"] = jit
    clean["TMPDIR"] = str(root / "_temp")
    clean.setdefault("HOME", str(root))
    clean.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    if os.getuid() == 0:
        clean["RUNNER_ALLOW_RUNASROOT"] = "1"
    if Path(TOOLS).is_dir():
        clean["AGENT_TOOLSDIRECTORY"] = TOOLS
    Path(clean["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    (root / "_work").mkdir(parents=True, exist_ok=True)
    return clean


def run_runner(
    jit: str,
    name: str = "",
    repo: str = "",
    idle: float = 300.0,
    lifetime: float = 3600.0,
) -> int:
    version = _version()
    archive = _tarball(version)
    root = Path(tempfile.mkdtemp(prefix="runner-"))
    process = None
    try:
        listener = _unpack(archive, root)
        process = subprocess.Popen(
            [str(listener), "run"],
            cwd=str(root),
            env=_environment(jit, root),
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        code = process.wait()
    finally:
        if process is not None and process.poll() is None:
            with contextlib.suppress(Exception):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        shutil.rmtree(root, ignore_errors=True)
    return OK if code == 0 else FAILED
