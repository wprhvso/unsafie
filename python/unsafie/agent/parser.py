import re
from collections.abc import Callable

FENCE_START_RE = re.compile(r"```(?:python)?\r?\n", re.IGNORECASE)


class MarkdownCodeParser:
    def __init__(self, on_block: Callable[[str], None]) -> None:
        self.on_block = on_block
        self.buffer = ""
        self.in_block = False

    def feed(self, chunk: str) -> None:
        if not chunk:
            return
        self.buffer += chunk
        self._parse()

    def _parse(self) -> None:
        while True:
            if not self.in_block:
                m = FENCE_START_RE.search(self.buffer)
                if not m:
                    break
                self.in_block = True
                self.buffer = self.buffer[m.end():]
            else:
                idx = self.buffer.find("```")
                if idx == -1:
                    break
                code = self.buffer[:idx]
                self.in_block = False
                self.buffer = self.buffer[idx + 3:]
                stripped = code.strip()
                if stripped:
                    self.on_block(stripped)

    def close(self) -> None:
        if self.in_block:
            code = self.buffer.strip()
            self.in_block = False
            self.buffer = ""
            if code:
                self.on_block(code)
