import os
import shutil
import socket
import subprocess
import time

RFB_PORT = 5900
DISPLAY = ":99"
WAIT = 15.0
BOOT = 10.0
SIZE = "1920x1080"
SOCKETS = "/tmp/.X11-unix"


def rfb_port(display: str = DISPLAY) -> int:
    return RFB_PORT


def listening(port: int, timeout: float = WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)


def running(display: str) -> bool:
    number = display.lstrip(":").split(".")[0]
    if not number:
        return False
    if os.path.exists(f"{SOCKETS}/X{number}"):
        return True
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.connect(f"\0/tmp/.X11-unix/X{number}")
            return True
    except OSError:
        return False


def ensure(size: str = SIZE, display: str = DISPLAY) -> str:
    if listening(RFB_PORT, 0.5):
        return ""
    existing = os.environ.get("DISPLAY") or (display if running(display) else "")
    if existing:
        return attach(existing, size)
    name, _ = start_display(size, display)
    if not name:
        return "no display server here"
    if listening(RFB_PORT, BOOT):
        return ""
    return f"display {name} is up but nothing serves rfb on {RFB_PORT}"


def start_display(size: str, display: str = DISPLAY) -> tuple[str, subprocess.Popen | None]:
    existing = os.environ.get("DISPLAY")
    if existing:
        attach(existing, size)
        return existing, None
    if running(display):
        attach(display, size)
        return display, None
    width, _, height = size.partition("x")
    kasm = shutil.which("Xkasmvnc")
    if kasm:
        process = subprocess.Popen(
            [
                kasm,
                display,
                "-geometry",
                f"{width}x{height}",
                "-depth",
                "24",
                "-rfbport",
                str(RFB_PORT),
                "-SecurityTypes",
                "None",
                "-interface",
                "127.0.0.1",
                "-AlwaysShared",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if listening(RFB_PORT, BOOT):
            _decorate(display)
            return display, process
        process.terminate()
    xvfb = shutil.which("Xvfb")
    if xvfb is None:
        return "", None
    process = subprocess.Popen(
        [xvfb, display, "-screen", "0", f"{width}x{height}x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _await(display)
    _decorate(display)
    attach(display, size)
    return display, process


def attach(display: str, size: str = SIZE) -> str:
    if not running(display):
        return f"there is no X display on {display}"
    kasm = shutil.which("Xkasmvnc")
    proxy = shutil.which("kasmxproxy")
    if kasm and proxy:
        width, _, height = size.partition("x")
        vnc_disp = ":98" if display != ":98" else ":96"
        if not listening(RFB_PORT, 0.5):
            subprocess.Popen(
                [
                    kasm,
                    vnc_disp,
                    "-geometry",
                    f"{width}x{height}",
                    "-depth",
                    "24",
                    "-rfbport",
                    str(RFB_PORT),
                    "-SecurityTypes",
                    "None",
                    "-interface",
                    "127.0.0.1",
                    "-AlwaysShared",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if listening(RFB_PORT, BOOT):
            pkill = shutil.which("pkill")
            if pkill:
                subprocess.run([pkill, "-f", f"kasmxproxy.*{display}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen(
                [proxy, "-a", display, "-v", vnc_disp],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ""
    x11vnc = shutil.which("x11vnc")
    if x11vnc is None:
        return "neither kasmvnc nor x11vnc is installed"
    if listening(RFB_PORT, 0.5):
        return ""
    subprocess.Popen(
        [
            x11vnc,
            "-display",
            display,
            "-rfbport",
            str(RFB_PORT),
            "-localhost",
            "-forever",
            "-shared",
            "-nopw",
            "-quiet",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "" if listening(RFB_PORT, BOOT) else "vnc did not come up"


def _await(display: str, timeout: float = BOOT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if running(display):
            return True
        time.sleep(0.2)
    return False


def _decorate(display: str) -> None:
    openbox = shutil.which("openbox")
    if openbox is None:
        return
    environment = dict(os.environ, DISPLAY=display)
    subprocess.Popen(
        [openbox],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
