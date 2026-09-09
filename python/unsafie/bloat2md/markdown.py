from collections.abc import Sequence
from typing import Final

MAX_PIPE_ROWS: Final = 30
MAX_PIPE_COLUMNS: Final = 10
MAX_RECORD_COLUMNS: Final = 15
HEADER_REPEAT: Final = 25


def cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _row(values: Sequence[object]) -> str:
    return f"| {' | '.join(cell(value) for value in values)} |"


def _rule(width: int) -> str:
    return f"|{'---|' * width}"


def _pipe(header: Sequence[object], rows: Sequence[Sequence[object]]) -> str:
    width = len(header)
    lines = [_row(header), _rule(width)]
    for index, values in enumerate(rows):
        if index and index % HEADER_REPEAT == 0:
            lines.extend((_row(header), _rule(width)))
        lines.append(_row(values))
    return "\n".join(lines)


def _records(header: Sequence[object], rows: Sequence[Sequence[object]]) -> str:
    blocks: list[str] = []
    for index, values in enumerate(rows, start=1):
        fields = [
            f"- {cell(name)}: {cell(value)}"
            for name, value in zip(header, values, strict=False)
            if cell(value)
        ]
        blocks.append(f"#{index}\n" + "\n".join(fields))
    return "\n\n".join(blocks)


def table(rows: Sequence[Sequence[object]]) -> str:
    if not rows:
        return ""
    header, *body = rows
    if len(header) > MAX_RECORD_COLUMNS or (
        len(header) > MAX_PIPE_COLUMNS and len(body) > MAX_PIPE_ROWS
    ):
        return _records(header, body)
    return _pipe(header, body)


def trim(rows: Sequence[Sequence[object]]) -> list[list[object]]:
    kept = [list(row) for row in rows]
    while kept and not any(cell(value) for value in kept[-1]):
        _ = kept.pop()
    if not kept:
        return []
    width = max(
        (index + 1 for row in kept for index, value in enumerate(row) if cell(value)),
        default=0,
    )
    return [row[:width] + [""] * (width - len(row[:width])) for row in kept]
