import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

PROTOCOL = 1


class FrameKind(StrEnum):
    HELLO = "hello"
    COMMAND = "command"
    STDIN = "stdin"
    CANCEL = "cancel"
    OUTPUT = "output"
    EXIT = "exit"
    PING = "ping"


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


def output(command_id: str, data: str, stream: Stream = Stream.OUT) -> Frame:
    return Frame(FrameKind.OUTPUT, command_id, {"stream": str(stream), "data": data})


def exited(command_id: str, code: int, seconds: float) -> Frame:
    return Frame(FrameKind.EXIT, command_id, {"code": code, "seconds": round(seconds, 3)})


def cancel(command_id: str) -> Frame:
    return Frame(FrameKind.CANCEL, command_id)
