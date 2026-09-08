import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from unsafie_sdk.chrome.cdp import Cdp, CdpError
from unsafie_sdk.chrome.ws import json_get
from unsafie_sdk.chrome import vnc

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
    raise BrowserError(
        "no chrome on this machine; install it with `unsafie setup chrome`"
    )


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
    """A display for Chrome, with a VNC server watching it from birth."""
    return vnc.start_display(size)


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
    endpoint = _wait_for_devtools(port)
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
    raise BrowserError(f"chrome did not open devtools in {BOOT_WAIT:.0f}s: {last}")


def connect(endpoint: str, timeout: float = 30.0) -> Cdp:
    try:
        return Cdp(endpoint, timeout)
    except Exception as broken:
        raise BrowserError(f"cannot reach the browser: {broken}") from None


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


def json_list(port: int) -> list[dict]:
    try:
        listing = json_get(f"http://127.0.0.1:{port}/json/list", timeout=5.0)
    except Exception:
        return []
    if not isinstance(listing, list):
        return []
    return [item for item in listing if item.get("type") == "page"]


def close_page(port: int, target_id: str) -> None:
    try:
        json_get(f"http://127.0.0.1:{port}/json/close/{target_id}", timeout=5.0)
    except Exception:
        return


def activate_page(port: int, target_id: str) -> None:
    try:
        json_get(f"http://127.0.0.1:{port}/json/activate/{target_id}", timeout=5.0)
    except Exception:
        return


def stop(state: dict) -> None:
    for key in ("pid", "xvfb_pid"):
        pid = state.get(key)
        if not pid:
            continue
        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass


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
        raise BrowserError("the browser has no page to drive")
    cdp = connect(endpoint)
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("DOM.enable")
    except CdpError:
        pass
    return cdp, endpoint
