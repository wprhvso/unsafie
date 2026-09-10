import base64
import contextlib
import json
import os
import secrets
import socket
import struct
import urllib.parse
import urllib.request

TEXT = 0x1
BINARY = 0x2
CLOSE = 0x8
PING = 0x9
PONG = 0xA
FIN = 0x80
MASK = 0x80
HANDSHAKE_LIMIT = 65536
GOODBYE = 1.0


class WsError(RuntimeError):
    pass


class WebSocket:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("ws", "http", "wss", "https"):
            msg = f"cannot open a websocket to {parsed.scheme}"
            raise WsError(msg)
        secure = parsed.scheme in ("wss", "https")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if secure else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        raw = socket.create_connection((host, port), timeout=timeout)
        if secure:
            import ssl
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        self.sock = raw
        self.sock.settimeout(timeout)
        self._buffer = b""
        self._handshake(host, port, path)

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        while b"\r\n\r\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                msg = "the browser closed the connection during the handshake"
                raise WsError(msg)
            self._buffer += chunk
            if len(self._buffer) > HANDSHAKE_LIMIT:
                msg = "handshake answer is absurdly large"
                raise WsError(msg)
        head, _, rest = self._buffer.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            msg = f"the browser refused the upgrade: {head.splitlines()[0]!r}"
            raise WsError(msg)
        self._buffer = rest

    def send(self, payload: str) -> None:
        self.send_frame(payload.encode(), TEXT)

    def send_bytes(self, data: bytes) -> None:
        self.send_frame(data, BINARY)

    def send_frame(self, data: bytes, opcode: int) -> None:
        header = bytearray([FIN | opcode])
        mask = os.urandom(4)
        size = len(data)
        if size < 126:
            header.append(MASK | size)
        elif size < 65536:
            header.append(MASK | 126)
            header += struct.pack("!H", size)
        else:
            header.append(MASK | 127)
            header += struct.pack("!Q", size)
        header += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def recv(self) -> str | None:
        payload = self.recv_bytes()
        return None if payload is None else payload.decode(errors="replace")

    def recv_bytes(self) -> bytes | None:
        while True:
            frame = self._frame()
            if frame is None:
                return None
            opcode, payload = frame
            if opcode in (TEXT, BINARY):
                return payload
            if opcode == PING:
                self._pong(payload)
            elif opcode == CLOSE:
                return None

    def _frame(self) -> tuple[int, bytes] | None:
        head = self._read(2)
        if head is None:
            return None
        opcode = head[0] & 0x0F
        size = head[1] & 0x7F
        if size == 126:
            more = self._read(2)
            if more is None:
                return None
            size = struct.unpack("!H", more)[0]
        elif size == 127:
            more = self._read(8)
            if more is None:
                return None
            size = struct.unpack("!Q", more)[0]
        payload = self._read(size) if size else b""
        if payload is None:
            return None
        return opcode, payload

    def _pong(self, payload: bytes) -> None:
        header = bytearray([FIN | PONG, MASK | len(payload)])
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(
            bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)),
        )

    def _read(self, size: int) -> bytes | None:
        while len(self._buffer) < size:
            try:
                chunk = self.sock.recv(65536)
            except TimeoutError:
                msg = "the browser stopped answering"
                raise WsError(msg) from None
            except OSError as broken:
                msg = f"the browser connection was closed: {broken}"
                raise WsError(msg) from None
            if not chunk:
                return None
            self._buffer += chunk
        taken, self._buffer = self._buffer[:size], self._buffer[size:]
        return taken

    def close(self) -> None:
        try:
            self.sock.settimeout(GOODBYE)
            self.sock.sendall(bytes([FIN | CLOSE, MASK | 0]) + os.urandom(4))
        except OSError:
            pass
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self.sock.close()


def json_get(url: str, timeout: float = 10.0) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as answer:
        return json.loads(answer.read())
