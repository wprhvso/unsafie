import json
import threading
import time
from typing import Any

from unsafie.chrome.ws import WebSocket, WsError


class CdpError(RuntimeError):
    pass


class Cdp:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        self.socket = WebSocket(url, timeout)
        self.timeout = timeout
        self._id = 0
        self._answers: dict[int, dict] = {}
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def close(self) -> None:
        self.socket.close()

    def call(self, method: str, params: dict | None = None, session: str | None = None) -> Any:
        with self._lock:
            self._id += 1
            message_id = self._id
            payload: dict[str, Any] = {"id": message_id, "method": method}
            if params:
                payload["params"] = params
            if session:
                payload["sessionId"] = session
            self.socket.send(json.dumps(payload))
            answer = self._wait(message_id)
        if "error" in answer:
            problem = answer["error"]
            msg = f"{method}: {problem.get('message')} ({problem.get('code')})"
            raise CdpError(msg)
        return answer.get("result", {})

    def _wait(self, message_id: int) -> dict:
        deadline = time.monotonic() + self.timeout
        while True:
            stored = self._answers.pop(message_id, None)
            if stored is not None:
                return stored
            if time.monotonic() > deadline:
                msg = f"the browser did not answer message {message_id}"
                raise CdpError(msg)
            raw = self.socket.recv()
            if raw is None:
                msg = "the browser closed the devtools connection"
                raise CdpError(msg)
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if "id" in message:
                self._answers[int(message["id"])] = message
                if len(self._answers) > 200:
                    self._answers.pop(next(iter(self._answers)), None)
            else:
                self._events.append(message)
                del self._events[:-200]

    def events(self, name: str | None = None) -> list[dict]:
        if name is None:
            return list(self._events)
        return [event for event in self._events if event.get("method") == name]

    def drain(self, seconds: float = 0.2) -> None:
        deadline = time.monotonic() + seconds
        self.socket.sock.settimeout(0.05)
        try:
            while time.monotonic() < deadline:
                try:
                    raw = self.socket.recv()
                except (WsError, TimeoutError, OSError):
                    return
                if raw is None:
                    return
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if "id" in message:
                    self._answers[int(message["id"])] = message
                    if len(self._answers) > 200:
                        self._answers.pop(next(iter(self._answers)), None)
                else:
                    self._events.append(message)
        finally:
            self.socket.sock.settimeout(self.timeout)
