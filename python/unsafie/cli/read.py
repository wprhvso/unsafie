import glob
import os
import sys
from pathlib import Path
from typing import Any

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
}


def parse_range(spec: str | None) -> tuple[int, int | None]:
    if not spec:
        return 1, None
    spec = spec.strip()
    if "-" in spec:
        parts = spec.split("-", 1)
        start = int(parts[0]) if parts[0].strip() else 1
        end = int(parts[1]) if parts[1].strip() else None
        return max(1, start), end
    if spec.isdigit():
        val = int(spec)
        return max(1, val), val
    return 1, None


def is_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data[:1024]:
        return True
    return False


def collect_paths(targets: list[str]) -> list[Path]:
    collected: list[Path] = []
    seen: set[Path] = set()

    for pattern in targets:
        matches = glob.glob(pattern, recursive=True)
        paths = [Path(m) for m in matches] if matches else [Path(pattern)]
        for p in paths:
            if not p.exists():
                collected.append(p)
                continue
            if p.is_file():
                if p not in seen:
                    seen.add(p)
                    collected.append(p)
            elif p.is_dir():
                for root, dirs, files in os.walk(p):
                    dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                    for file in sorted(files):
                        fp = Path(root) / file
                        if fp not in seen:
                            seen.add(fp)
                            collected.append(fp)
    return collected


def read(
    paths: list[str],
    *,
    lines: str | None = None,
    max_lines: int = 2000,
    raw: bool = False,
) -> dict[str, Any]:
    if not paths:
        return {"ok": False, "error": "at least one path required"}

    target_paths = collect_paths(paths)
    if not target_paths:
        return {"ok": False, "error": "no matching files found"}

    start_line, end_line = parse_range(lines)
    rendered_blocks: list[str] = []
    file_results: list[dict[str, Any]] = []
    total_lines_read = 0

    for path in target_paths:
        if not path.exists():
            err_msg = f"=== {path} [ERROR: file not found] ==="
            rendered_blocks.append(err_msg)
            file_results.append({"path": str(path), "error": "file not found"})
            continue

        if not path.is_file():
            continue

        try:
            raw_bytes = path.read_bytes()
        except Exception as e:
            err_msg = f"=== {path} [ERROR: cannot read: {e}] ==="
            rendered_blocks.append(err_msg)
            file_results.append({"path": str(path), "error": str(e)})
            continue

        if is_binary(raw_bytes):
            msg = f"=== {path} [BINARY FILE: {len(raw_bytes)} bytes] ==="
            rendered_blocks.append(msg)
            file_results.append({"path": str(path), "binary": True, "bytes": len(raw_bytes)})
            continue

        try:
            content_str = raw_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            err_msg = f"=== {path} [ERROR: decode failed: {e}] ==="
            rendered_blocks.append(err_msg)
            file_results.append({"path": str(path), "error": str(e)})
            continue

        all_lines = content_str.splitlines()
        total_count = len(all_lines)

        actual_start = min(start_line, total_count) if total_count > 0 else 1
        if end_line is not None:
            actual_end = min(end_line, total_count)
        else:
            actual_end = total_count

        if actual_end < actual_start:
            slice_lines: list[str] = []
        else:
            slice_lines = all_lines[actual_start - 1 : actual_end]

        truncated = False
        if len(slice_lines) > max_lines:
            slice_lines = slice_lines[:max_lines]
            actual_end = actual_start + len(slice_lines) - 1
            truncated = True

        width = len(str(actual_end)) if actual_end > 0 else 1
        formatted_slice: list[str] = []
        for idx, line in enumerate(slice_lines, start=actual_start):
            formatted_slice.append(f"{idx:>{width}} | {line}")

        formatted_content = "\n".join(formatted_slice)

        header = f"=== {path} ({total_count} lines"
        if actual_start > 1 or (end_line is not None and actual_end < total_count):
            header += f", lines {actual_start}-{actual_end}"
        if truncated:
            header += f", truncated to {max_lines} lines"
        header += ") ==="

        rendered_blocks.append(header)
        if formatted_content:
            rendered_blocks.append(formatted_content)
        else:
            rendered_blocks.append("  (empty)")

        total_lines_read += len(slice_lines)
        file_results.append(
            {
                "path": str(path),
                "total_lines": total_count,
                "start": actual_start,
                "end": actual_end,
                "lines_read": len(slice_lines),
                "truncated": truncated,
            }
        )

    full_rendered = "\n".join(rendered_blocks)

    if raw:
        sys.stdout.write(full_rendered + "\n")
        sys.stdout.flush()

    return {
        "ok": True,
        "files": file_results,
        "count": len(file_results),
        "total_lines_read": total_lines_read,
        "rendered": full_rendered,
    }
