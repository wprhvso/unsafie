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


def rfb_port(display: str = DISPLAY) -> int:
    """The RFB port of a display: :97 is served on 5900 + 97 % 100 by habit."""
    return RFB_PORT


def listening(port: int, timeout: float = WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def start_display(size: str, display: str = DISPLAY) -> tuple[str, subprocess.Popen | None]:
    """Bring up a display Chrome can draw on, with a VNC server on it.

    Returns the display name and the process owning it (None when we joined a
    display that was already there).
    """
    if os.environ.get("DISPLAY"):
        existing = os.environ["DISPLAY"]
        attach(existing, size)
        return existing, None
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
        if listening(RFB_PORT):
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
    time.sleep(1.0)
    _decorate(display)
    attach(display, size)
    return display, process


def attach(display: str, size: str = "1920x1080") -> str:
    """Put a VNC server on a display that already exists (x11vnc)."""
    try:
        with socket.create_connection(("127.0.0.1", RFB_PORT), timeout=0.5):
            return ""
    except OSError:
        pass
    x11vnc = shutil.which("x11vnc")
    if x11vnc is None:
        return "no x11vnc and no kasmvnc here; run `unsafie setup kasmvnc`"
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
    return "" if listening(RFB_PORT) else "the vnc server did not come up"


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
