"""The VNC server that shows what the browser is doing.

One display, one server: whatever X server Chrome draws on is the very one a
viewer connects to. KasmVNC provides its own X server (Xkasmvnc), so when it is
installed the display *is* the VNC session; otherwise a plain Xvfb is dressed
with x11vnc. Either way a raw RFB socket ends up on :attr:`RFB_PORT`, which is
exactly what the /m/<slug> tunnel pipes bytes to.
"""

import os
import shutil
import socket
import subprocess
import time

RFB_PORT = 5900
DISPLAY = ":97"
WAIT = 15.0
BOOT = 10.0
SIZE = "1920x1080"
SOCKETS = "/tmp/.X11-unix"


def rfb_port(display: str = DISPLAY) -> int:
    """The RFB port of a display: :97 is served on 5900 + 97 % 100 by habit."""
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
    """Whether an X server already owns that display."""
    number = display.lstrip(":").split(".")[0]
    return bool(number) and os.path.exists(f"{SOCKETS}/X{number}")


def ensure(size: str = SIZE, display: str = DISPLAY) -> str:
    """Guarantee a desktop with raw RFB on RFB_PORT. Returns "" or the reason it failed."""
    if listening(RFB_PORT, 0.5):
        return ""
    existing = os.environ.get("DISPLAY") or (display if running(display) else "")
    if existing:
        return attach(existing, size)
    name, _ = start_display(size, display)
    if not name:
        return "no display server here; run `unsafie-machine setup xvfb kasmvnc`"
    if listening(RFB_PORT, BOOT):
        return ""
    return f"display {name} is up but nothing serves rfb on {RFB_PORT}"


def start_display(size: str, display: str = DISPLAY) -> tuple[str, subprocess.Popen | None]:
    """Bring up a display Chrome can draw on, with a VNC server on it.

    Returns the display name and the process owning it (None when we joined a
    display that was already there).
    """
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
    """Put a VNC server on a display that already exists (x11vnc)."""
    if listening(RFB_PORT, 0.5):
        return ""
    if not running(display):
        return f"there is no X display on {display}"
    x11vnc = shutil.which("x11vnc")
    if x11vnc is None:
        return "x11vnc is not installed; run `unsafie-machine setup xvfb`"
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
    return "" if listening(RFB_PORT, BOOT) else "x11vnc did not come up"


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
