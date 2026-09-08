import os
import pty
import shutil
import socket
import struct
import subprocess
import sys
import threading

from unsafie_sdk.chrome.ws import WebSocket

CHUNK = 65536
VNC_WAIT = 20.0


def serve_tunnel(url: str, kind: str, port: int) -> None:
    socket_to_server = WebSocket(url, timeout=600.0)
    try:
        if kind == "term":
            _terminal(socket_to_server)
        else:
            _tcp(socket_to_server, port)
    finally:
        socket_to_server.close()


def _tcp(link: WebSocket, port: int) -> None:
    local = socket.create_connection(("127.0.0.1", port), timeout=VNC_WAIT)
    local.settimeout(None)
    stop = threading.Event()

    def to_server() -> None:
        try:
            while not stop.is_set():
                data = local.recv(CHUNK)
                if not data:
                    return
                link.send_bytes(data)
        except OSError:
            return
        finally:
            stop.set()

    reader = threading.Thread(target=to_server, daemon=True)
    reader.start()
    try:
        while not stop.is_set():
            data = link.recv_bytes()
            if data is None:
                return
            local.sendall(data)
    except OSError:
        return
    finally:
        stop.set()
        local.close()


def _terminal(link: WebSocket) -> None:
    shell = os.environ.get("SHELL") or "/bin/bash"
    pid, master = pty.fork()
    if pid == 0:
        os.environ.setdefault("TERM", "xterm-256color")
        os.chdir(os.path.expanduser("~"))
        os.execvp(shell, [shell, "-l"])
        os._exit(127)
    stop = threading.Event()

    def to_server() -> None:
        try:
            while not stop.is_set():
                data = os.read(master, CHUNK)
                if not data:
                    return
                link.send_bytes(data)
        except OSError:
            return
        finally:
            stop.set()

    reader = threading.Thread(target=to_server, daemon=True)
    reader.start()
    try:
        while not stop.is_set():
            data = link.recv_bytes()
            if data is None:
                return
            if data[:1] == b"\x1b" and data[1:2] == b"]" and data[2:8] == b"resize":
                _resize(master, data)
                continue
            os.write(master, data)
    except OSError:
        return
    finally:
        stop.set()
        try:
            os.close(master)
        except OSError:
            pass
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def _resize(master: int, payload: bytes) -> None:
    import fcntl
    import termios

    try:
        _, rest = payload.split(b"resize", 1)
        cols, rows = rest.decode(errors="ignore").strip().split("x")
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
    except (ValueError, OSError):
        return


def start_vnc(display: str, port: int, size: str = "1920x1080") -> str:
    binary = shutil.which("Xkasmvnc") or shutil.which("kasmvncserver")
    if binary is None:
        return "kasmvnc is not installed; run `unsafie setup kasmvnc`"
    done = subprocess.run(
        [
            "kasmvncserver",
            "start",
            display,
            "-select-de",
            "openbox",
            "-websocketPort",
            str(port),
            "-geometry",
            size,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        return done.stderr.strip()[:200] or "kasmvnc refused to start"
    sys.stderr.write(f"[machine] kasmvnc on {display}, websocket port {port}\n")
    return ""
