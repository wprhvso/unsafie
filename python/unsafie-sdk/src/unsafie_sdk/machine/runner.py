import os
import platform
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
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
LISTENING = "Listening for Jobs"
STARTED = "Running job:"
FINISHED = "completed with result:"
CACHE = Path(os.environ.get("UNSAFIE_RUNNER_CACHE") or "/opt/unsafie/runner")
POLL = 1.0
GRACE = 20.0
BUSY_GRACE = 400.0
SMALL = 1 << 20


def _arch() -> str:
    machine = platform.machine().lower()
    if machine not in ARCHES:
        raise RuntimeError(f"there is no actions runner for {machine}")
    return ARCHES[machine]


def _version() -> str:
    request = urllib.request.Request(RELEASES, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as answer:
        landed = answer.url
    tag = landed.rsplit("/v", 1)[-1].strip("/") if "/tag/v" in landed else ""
    if not tag:
        raise RuntimeError(f"could not tell the runner version from {landed}")
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
    if part.stat().st_size < SMALL:
        part.unlink(missing_ok=True)
        raise RuntimeError("the runner archive came out suspiciously small")
    part.replace(target)
    return target


def _unpack(archive: Path, root: Path) -> Path:
    with tarfile.open(archive) as tar:
        tar.extractall(root, filter="data")
    listener = root / LISTENER
    if not listener.exists():
        raise RuntimeError(f"the archive has no {LISTENER}")
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


def _say(text: str) -> None:
    print(text, flush=True)


class Progress:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.job = ""
        self.jobs = 0
        self.results: list[str] = []
        self.listening = False
        self.born = time.monotonic()

    def busy(self) -> bool:
        with self.lock:
            return bool(self.job)

    def read(self, text: str) -> None:
        with self.lock:
            if LISTENING in text and not self.listening:
                self.listening = True
                _say("[runner] listening for jobs")
            elif STARTED in text:
                self.job = text.split(STARTED, 1)[1].strip()
                self.jobs += 1
                _say(f"[runner] job started: {self.job}")
            elif FINISHED in text and self.job:
                result = text.rsplit(FINISHED, 1)[1].strip()
                self.results.append(result)
                _say(f"[runner] job finished: {self.job} -> {result}")
                self.job = ""


def _pump(stream, progress: Progress) -> None:
    for raw in iter(stream.readline, ""):
        text = raw.rstrip("\n")
        _say(text)
        progress.read(text)


def _watchdog(
    process: subprocess.Popen, progress: Progress, idle: float, lifetime: float, done: threading.Event
) -> None:
    while not done.wait(POLL):
        if process.poll() is not None:
            return
        waited = time.monotonic() - progress.born
        overdue = lifetime and waited > lifetime
        unused = idle and progress.listening and not progress.busy() and waited > idle
        if not (overdue or unused):
            continue
        _say(f"[runner] stopping: {'lifetime' if overdue else 'idle'}")
        with_grace = BUSY_GRACE if progress.busy() else GRACE
        try:
            process.terminate()
        except OSError:
            return
        if not done.wait(with_grace) and process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        return


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
    progress = Progress()
    done = threading.Event()
    _say(f"[runner] {name or 'runner'} for {repo or 'a repository'} on v{version}")
    process = None
    try:
        listener = _unpack(archive, root)
        process = subprocess.Popen(
            [str(listener), "run"],
            cwd=str(root),
            env=_environment(jit, root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        guard = threading.Thread(
            target=_watchdog, args=(process, progress, idle, lifetime, done), daemon=True
        )
        guard.start()
        reader = threading.Thread(target=_pump, args=(process.stdout, progress), daemon=True)
        reader.start()
        code = process.wait()
        reader.join(5.0)
    finally:
        done.set()
        if process is not None and process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        shutil.rmtree(root, ignore_errors=True)
    _say(
        f"[runner] gone after {time.monotonic() - progress.born:.0f}s, "
        f"jobs={progress.jobs} results={','.join(progress.results) or 'none'}"
    )
    return OK if code == 0 or progress.jobs else FAILED
