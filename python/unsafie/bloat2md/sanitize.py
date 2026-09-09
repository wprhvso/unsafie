import re
import unicodedata
from dataclasses import dataclass
from typing import Final

_TAGS: Final = re.compile("[\U000e0000-\U000e007f]")
_BIDI: Final = re.compile("[\\u202a-\\u202e\\u2066-\\u2069]")
_MEANINGLESS_WIDTH: Final = re.compile("[\\u00ad\\u200b\\u2060\\ufeff]")
_JOINER_RUNS: Final = re.compile("[\\u200c\\u200d]{3,}")
_SURROGATES: Final = re.compile("[\ud800-\udfff]")
_CONTROLS: Final = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BLANK_RUNS: Final = re.compile("\n{4,}")
_TRAILING: Final = re.compile("[ \t]+\n")

_RULES: Final = (
    ("tags", _TAGS),
    ("bidi", _BIDI),
    ("zero_width", _MEANINGLESS_WIDTH),
    ("joiner_runs", _JOINER_RUNS),
    ("surrogates", _SURROGATES),
    ("controls", _CONTROLS),
)


@dataclass(frozen=True, slots=True)
class Cleaned:
    text: str
    dropped: dict[str, int]


def clean(text: str) -> Cleaned:
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    dropped: dict[str, int] = {}
    for name, pattern in _RULES:
        text, count = pattern.subn("", text)
        if count:
            dropped[name] = count

    text = unicodedata.normalize("NFC", text)
    text = _TRAILING.sub("\n", text)
    text = _BLANK_RUNS.sub("\n\n\n", text)
    return Cleaned(text=text.strip(), dropped=dropped)


def clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = limit * 3 // 4
    tail = limit - head
    skipped = len(text) - limit
    notice = f"[... {skipped} characters skipped ...]"
    return f"{text[:head].rstrip()}\n\n{notice}\n\n{text[-tail:].lstrip()}", True
