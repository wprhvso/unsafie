import re
import sys
from pathlib import Path
from typing import Any

GIT_DIFF_BLOCK_RE = re.compile(
    r"<<<<<<<\s*SEARCH\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>>\s*REPLACE",
    re.DOTALL,
)

ALT_BLOCK_RE = re.compile(
    r"===\s*SEARCH\s*===\r?\n(.*?)\r?\n===\s*REPLACE\s*===\r?\n(.*)",
    re.DOTALL,
)


def _parse_stdin_blocks(raw_input: str) -> tuple[str, str] | None:
    match = GIT_DIFF_BLOCK_RE.search(raw_input)
    if match:
        return match.group(1), match.group(2)

    match = ALT_BLOCK_RE.search(raw_input)
    if match:
        replace_part = match.group(2)
        end_marker = re.search(r"\r?\n===\s*END\s*===", replace_part)
        if end_marker:
            replace_part = replace_part[: end_marker.start()]
        return match.group(1), replace_part

    if "=======" in raw_input:
        parts = raw_input.split("=======", 1)
        search_part = parts[0].replace("<<<<<<< SEARCH", "").replace("<<<<<<<", "").strip("\r\n")
        replace_part = parts[1].replace(">>>>>>> REPLACE", "").replace(">>>>>>>", "").strip("\r\n")
        return search_part, replace_part

    return None


def run(
    path: str,
    search: str | None = None,
    replace: str | None = None,
) -> dict[str, Any]:
    if not path:
        return {"ok": False, "error": "file path is required"}

    target = Path(path)
    if not target.is_file():
        return {"ok": False, "error": f"file not found: {path}"}

    if search is None or replace is None:
        raw_stdin = sys.stdin.read()
        parsed = _parse_stdin_blocks(raw_stdin)
        if parsed:
            search, replace = parsed
        else:
            return {
                "ok": False,
                "error": (
                    "could not parse search and replace blocks from stdin. "
                    "Use '<<<<<<< SEARCH\\nold\\n=======\\nnew\\n>>>>>>> REPLACE' "
                    "or pass search and replace as arguments."
                ),
            }

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"cannot read {path}: {e}"}

    if search not in content:
        # Check if line-ending mismatch (\r\n vs \n)
        normalized_content = content.replace("\r\n", "\n")
        normalized_search = search.replace("\r\n", "\n")
        if normalized_search in normalized_content:
            content = normalized_content
            search = normalized_search
        else:
            # Provide snippet hint
            search_first_line = search.strip().splitlines()[0] if search.strip() else ""
            return {
                "ok": False,
                "error": f"search block not found in {path}. First line searched: '{search_first_line[:80]}'",
                "path": str(target),
            }

    count = content.count(search)
    new_content = content.replace(search, replace, 1)

    try:
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"cannot write {path}: {e}"}

    return {
        "ok": True,
        "path": str(target),
        "replaced": True,
        "occurrences_found": count,
        "new_lines": len(new_content.splitlines()),
    }
