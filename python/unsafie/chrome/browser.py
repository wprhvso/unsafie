import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from unsafie.chrome import vnc
from unsafie.chrome.cdp import Cdp, CdpError
from unsafie.chrome.ws import json_get

CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
)
STATE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/run") / "unsafie"
PROFILES = Path.home() / ".local" / "share" / "unsafie" / "profiles"
BOOT_WAIT = 30.0
FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-features=Translate,MediaRouter,OptimizationHints",
    "--disable-dev-shm-usage",
    "--password-store=basic",
    "--no-sandbox",
)


class BrowserError(RuntimeError):
    pass


def binary() -> str:
    for name in CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    msg = "no chrome on this machine"
    raise BrowserError(msg)


def state_dir() -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE


def profile_dir(name: str | None) -> Path:
    if not name:
        return state_dir() / "profile-scratch"
    target = PROFILES / name
    target.mkdir(parents=True, exist_ok=True)
    return target


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _display(size: str) -> tuple[str, subprocess.Popen | None]:
    return vnc.start_display(size)


def _kill_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(OSError):
            proc.terminate()
    try:
        proc.wait(timeout=1.0)
    except (subprocess.TimeoutExpired, OSError):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(OSError):
                proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            proc.wait(timeout=1.0)


def launch(profile: str | None, size: str, headless: bool) -> dict:
    port = _free_port()
    data = profile_dir(profile)
    display, xvfb = ("", None) if headless else _display(size)
    width, _, height = size.partition("x")
    line = [
        binary(),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={data}",
        f"--window-size={width},{height}",
        *FLAGS,
        "about:blank",
    ]
    if headless or not display:
        line.insert(1, "--headless=new")
    environment = dict(os.environ)
    if display:
        environment["DISPLAY"] = display
    process = subprocess.Popen(
        line,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        endpoint = _wait_for_devtools(port)
    except Exception:
        _kill_process(process)
        if xvfb:
            _kill_process(xvfb)
        raise
    return {
        "pid": process.pid,
        "port": port,
        "endpoint": endpoint,
        "profile": profile or "",
        "profile_dir": str(data),
        "display": display,
        "xvfb_pid": xvfb.pid if xvfb else None,
        "headless": bool(headless or not display),
        "size": size,
        "vnc_port": vnc.RFB_PORT if display else None,
        "started_at": time.time(),
    }


def _wait_for_devtools(port: int) -> str:
    deadline = time.monotonic() + BOOT_WAIT
    last = ""
    while time.monotonic() < deadline:
        try:
            version = json_get(f"http://127.0.0.1:{port}/json/version", timeout=2.0)
        except Exception as broken:
            last = str(broken)
            time.sleep(0.2)
            continue
        if isinstance(version, dict) and version.get("webSocketDebuggerUrl"):
            return str(version["webSocketDebuggerUrl"])
        time.sleep(0.2)
    msg = f"chrome did not open devtools in {BOOT_WAIT:.0f}s: {last}"
    raise BrowserError(msg)


def connect(endpoint: str, timeout: float = 30.0) -> Cdp:
    try:
        return Cdp(endpoint, timeout)
    except Exception as broken:
        msg = f"cannot reach the browser: {broken}"
        raise BrowserError(msg) from None


def page_target(port: int) -> str | None:
    try:
        targets = json_get(f"http://127.0.0.1:{port}/json/list", timeout=5.0)
    except Exception:
        return None
    if not isinstance(targets, list):
        return None
    for target in targets:
        if target.get("type") == "page":
            return str(target.get("webSocketDebuggerUrl") or "")
    return None


def new_page(port: int, url: str = "about:blank") -> str | None:
    try:
        created = json_get(f"http://127.0.0.1:{port}/json/new?{url}", timeout=5.0)
    except Exception:
        return None
    if isinstance(created, dict):
        return str(created.get("webSocketDebuggerUrl") or "")
    return None


def stop(state: dict) -> None:
    for key in ("pid", "xvfb_pid"):
        pid = state.get(key)
        if not pid:
            continue
        try:
            target_pid = int(pid)
            pgid = os.getpgid(target_pid)
            os.killpg(pgid, signal.SIGTERM)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                try:
                    os.kill(target_pid, 0)
                    time.sleep(0.05)
                except ProcessLookupError:
                    break
            else:
                os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(OSError):
                os.kill(int(pid), signal.SIGKILL)
    pkill = shutil.which("pkill")
    if pkill and not state.get("headless"):
        subprocess.run([pkill, "-f", f"x11vnc.*{vnc.RFB_PORT}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def state_file() -> Path:
    return state_dir() / "chrome.json"


def save(state: dict) -> None:
    state_file().write_text(json.dumps(state), encoding="utf-8")


def load() -> dict | None:
    target = state_file()
    if not target.is_file():
        return None
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None
    pid = state.get("pid")
    if pid and not _alive(int(pid)):
        target.unlink(missing_ok=True)
        return None
    return state


def forget() -> None:
    state_file().unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def session(state: dict) -> tuple[Cdp, str]:
    endpoint = page_target(int(state["port"])) or new_page(int(state["port"]))
    if not endpoint:
        msg = "the browser has no page to drive"
        raise BrowserError(msg)
    cdp = connect(endpoint)
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("DOM.enable")
    except CdpError:
        pass
    return cdp, endpoint
