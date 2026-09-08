import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

PROTOCOL = 1


class FrameKind(StrEnum):
    HELLO = "hello"
    COMMAND = "command"
    PYTHON = "python"
    STDIN = "stdin"
    CANCEL = "cancel"
    OUTPUT = "output"
    EXIT = "exit"
    PING = "ping"
    ASSIGN = "assign"
    SHUTDOWN = "shutdown"


class Stream(StrEnum):
    OUT = "out"
    ERR = "err"


@dataclass(frozen=True, slots=True)
class Frame:
    kind: FrameKind
    id: str = ""
    body: dict[str, Any] = field(default_factory=dict)


def encode(frame: Frame) -> str:
    payload: dict[str, Any] = {"kind": str(frame.kind)}
    if frame.id:
        payload["id"] = frame.id
    payload.update(frame.body)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode(line: str) -> Frame | None:
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        kind = FrameKind(payload.pop("kind", ""))
    except ValueError:
        return None
    return Frame(kind, str(payload.pop("id", "")), payload)


def hello(machine: str, protocol: int = PROTOCOL, **facts: Any) -> Frame:
    return Frame(FrameKind.HELLO, machine, {"protocol": protocol, **facts})


def command(
    command_id: str,
    line: str,
    cwd: str | None = None,
    timeout: float | None = None,
    stdin: str | None = None,
    background: bool = False,
) -> Frame:
    body: dict[str, Any] = {"command": line, "background": background}
    if cwd:
        body["cwd"] = cwd
    if timeout:
        body["timeout"] = timeout
    if stdin:
        body["stdin"] = stdin
    return Frame(FrameKind.COMMAND, command_id, body)


def python(block_id: str, code: str, timeout: float | None = None, reset: bool = False) -> Frame:
    body: dict[str, Any] = {"code": code, "reset": reset}
    if timeout:
        body["timeout"] = timeout
    return Frame(FrameKind.PYTHON, block_id, body)


def output(command_id: str, data: str, stream: Stream = Stream.OUT) -> Frame:
    return Frame(FrameKind.OUTPUT, command_id, {"stream": str(stream), "data": data})


def exited(command_id: str, code: int, seconds: float) -> Frame:
    return Frame(FrameKind.EXIT, command_id, {"code": code, "seconds": round(seconds, 3)})


def cancel(command_id: str) -> Frame:
    return Frame(FrameKind.CANCEL, command_id)


def assign(
    token: str,
    chat_id: int | None = None,
    user_id: int | None = None,
    alias: str | None = None,
    turn: str | None = None,
) -> Frame:
    body: dict[str, Any] = {"token": token}
    if chat_id is not None:
        body["chat"] = chat_id
    if user_id is not None:
        body["user"] = user_id
    if alias:
        body["alias"] = alias
    if turn:
        body["turn"] = turn
    return Frame(FrameKind.ASSIGN, "", body)


def shutdown(reason: str = "released") -> Frame:
    return Frame(FrameKind.SHUTDOWN, "", {"reason": reason})
