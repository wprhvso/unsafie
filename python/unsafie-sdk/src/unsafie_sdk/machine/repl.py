import ast
import asyncio
import ctypes
import io
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unsafie_sdk.errors import StopTurn

MAX_REPR = 8000


@dataclass
class Outcome:
    ok: bool
    seconds: float
    error: str | None = None
    value_repr: str | None = None


class Writer(io.TextIOBase):
    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink

    def write(self, text: str) -> int:
        if text:
            self._sink(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


@dataclass
class Repl:
    """A living python namespace: variables, imports and state stay between blocks."""

    sink: Callable[[str], None]
    namespace: dict[str, Any] = field(default_factory=dict)
    loop: asyncio.AbstractEventLoop | None = None
    thread: threading.Thread | None = None
    blocks: int = 0

    def __post_init__(self) -> None:
        self.namespace.setdefault("__name__", "__unsafie__")
        self.namespace.setdefault("__builtins__", __builtins__)
        self.preload()

    def preload(self) -> None:
        import unsafie_sdk

        self.namespace.update(
            {name: getattr(unsafie_sdk, name) for name in unsafie_sdk.__all__},
            unsafie=unsafie_sdk,
            u=unsafie_sdk,
            Path=Path,
        )
        for module in ("os", "sys", "json", "re", "time", "math", "random", "subprocess", "shutil"):
            try:
                self.namespace.setdefault(module, __import__(module))
            except ImportError:
                continue

    def reset(self) -> None:
        self.namespace.clear()
        self.__post_init__()

    def run(self, code: str, timeout: float | None = None) -> Outcome:
        started = time.monotonic()
        self.blocks += 1
        stdout, stderr = sys.stdout, sys.stderr
        writer = Writer(self.sink)
        sys.stdout = sys.stderr = writer
        try:
            value = self._execute(code, timeout)
        except StopTurn:
            sys.stdout, sys.stderr = stdout, stderr
            return Outcome(True, time.monotonic() - started)
        except BaseException as failure:  # noqa: BLE001 - the traceback is the answer
            sys.stdout, sys.stderr = stdout, stderr
            text = _traceback(failure)
            self.sink(text if text.endswith("\n") else text + "\n")
            return Outcome(False, time.monotonic() - started, error=_last_line(text))
        finally:
            sys.stdout, sys.stderr = stdout, stderr
        shown = None
        if value is not None:
            shown = _short(repr(value))
            self.sink(shown + "\n")
            self.namespace["_"] = value
        return Outcome(True, time.monotonic() - started, value_repr=shown)

    def _execute(self, code: str, timeout: float | None) -> Any:
        tree = ast.parse(code, filename="<block>", mode="exec")
        if not tree.body:
            return None
        *head, tail = tree.body
        flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
        if head:
            block = ast.Module(body=head, type_ignores=[])
            self._maybe_await(compile(block, "<block>", "exec", flags=flags), timeout)
        if isinstance(tail, ast.Expr):
            last = ast.Expression(body=tail.value)
            return self._maybe_await(compile(last, "<block>", "eval", flags=flags), timeout)
        block = ast.Module(body=[tail], type_ignores=[])
        self._maybe_await(compile(block, "<block>", "exec", flags=flags), timeout)
        return None

    def _maybe_await(self, program, timeout: float | None) -> Any:
        result = eval(program, self.namespace)  # noqa: S307 - this is the point of a repl
        if asyncio.iscoroutine(result):
            return self._await(result, timeout)
        return result

    def _await(self, coroutine, timeout: float | None) -> Any:
        loop = self._loop()
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result(timeout)

    def _loop(self) -> asyncio.AbstractEventLoop:
        if self.loop is not None and not self.loop.is_closed():
            return self.loop
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="repl-loop", daemon=True)
        self.thread.start()
        return self.loop


def interrupt(thread: threading.Thread) -> bool:
    """Raise KeyboardInterrupt inside a running block."""
    if not thread.is_alive() or thread.ident is None:
        return False
    raised = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread.ident), ctypes.py_object(KeyboardInterrupt)
    )
    return raised == 1


def _traceback(failure: BaseException) -> str:
    """The traceback as the author of the block should see it: without this file in the way."""
    here = __file__
    entries = traceback.extract_tb(failure.__traceback__)
    kept = [entry for entry in entries if entry.filename != here]
    lines = ["Traceback (most recent call last):\n"]
    lines += traceback.format_list(kept or entries)
    lines += traceback.format_exception_only(type(failure), failure)
    return "".join(lines)


def _short(text: str) -> str:
    return text if len(text) <= MAX_REPR else text[:MAX_REPR] + f"… ({len(text)} chars)"


def _last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1][:300] if lines else "failed"
