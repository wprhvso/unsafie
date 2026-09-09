import re

BLOCK_RE = re.compile(r"```(?:bash|sh|shell)?\r?\n(.*?)\r?\n```", re.IGNORECASE | re.DOTALL)
STRIP_START_RE = re.compile(r"^\s*```(?:bash|sh|shell)?\r?\n?", re.IGNORECASE)
STRIP_END_RE = re.compile(r"\r?\n?```\s*$", re.IGNORECASE)


def extract_code(text: str | None) -> str:
    if not text:
        return ""
    match = BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()
    if STRIP_START_RE.search(text):
        code = STRIP_START_RE.sub("", text)
        code = STRIP_END_RE.sub("", code)
        return code.strip()
    return ""
