import contextlib
import os
import pty
import socket
import struct
import threading

from unsafie.chrome import vnc
from unsafie.chrome.ws import WebSocket

CHUNK = 65536
DIAL_WAIT = 20.0


class TunnelError(RuntimeError):
    pass


def serve_tunnel(url: str, kind: str, port: int) -> None:
    local = None if kind == "term" else dial(port)
    link = WebSocket(url, timeout=600.0)
    try:
        if local is None:
            _terminal(link)
        else:
            _tcp(link, local)
    finally:
        link.close()
        if local is not None:
            local.close()


def dial(port: int) -> socket.socket:
    if port == vnc.RFB_PORT:
        problem = vnc.ensure()
        if problem and not vnc.listening(vnc.RFB_PORT, 2.0):
            msg = f"no desktop on this machine: {problem}"
            raise TunnelError(msg)
    try:
        local = socket.create_connection(("127.0.0.1", port), timeout=DIAL_WAIT)
    except OSError as broken:
        msg = f"nothing answers on 127.0.0.1:{port} ({broken})"
        raise TunnelError(msg) from None
    local.settimeout(None)
    return local


def _tcp(link: WebSocket, local: socket.socket) -> None:
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
        with contextlib.suppress(OSError):
            os.close(master)
        with contextlib.suppress(OSError):
            os.kill(pid, 15)
        with contextlib.suppress(OSError):
            os.waitpid(pid, os.WNOHANG)


def _resize(master: int, payload: bytes) -> None:
    import fcntl
    import termios

    try:
        _, rest = payload.split(b"resize", 1)
        cols, rows = rest.decode(errors="ignore").strip().split("x")
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
    except (ValueError, OSError):
        return
