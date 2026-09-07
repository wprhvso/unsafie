import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Out:
    json_mode: bool = False
    quiet: bool = False
    color: bool = True

    def line(self, text: str = "") -> None:
        if not self.quiet:
            sys.stdout.write(text + "\n")

    def dim(self, text: str) -> str:
        return f"\033[2m{text}\033[0m" if self.color else text

    def bold(self, text: str) -> str:
        return f"\033[1m{text}\033[0m" if self.color else text

    def send(self, data: Any, text: str | Sequence[str] | None = None) -> None:
        if self.json_mode:
            sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
            return
        if text is None:
            self.line(str(data))
            return
        for row in [text] if isinstance(text, str) else text:
            self.line(row)

    def table(self, rows: Sequence[Sequence[str]], headers: Sequence[str] = ()) -> None:
        body = [list(headers)] + [list(row) for row in rows] if headers else [list(r) for r in rows]
        if not body:
            return
        widths = [max(len(str(row[i])) for row in body) for i in range(len(body[0]))]
        for index, row in enumerate(body):
            rendered = "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
            self.line(self.bold(rendered) if headers and index == 0 else rendered)

    def problem(self, message: str, hint: str = "") -> None:
        if self.json_mode:
            payload = {"error": message}
            if hint:
                payload["hint"] = hint
            sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
            return
        sys.stderr.write(f"error: {message}\n")
        if hint:
            sys.stderr.write(f"       {hint}\n")


def colors_wanted() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()
