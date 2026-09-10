import io
from typing import Final

import python_calamine as calamine

from unsafie.bloat2md.domain import ConversionError, Payload
from unsafie.bloat2md.markdown import table, trim
from unsafie.bloat2md.sanitize import clean

_VISIBLE: Final = calamine.SheetVisibleEnum.Visible
MAX_ROWS: Final = 2000


def convert(raw: bytes) -> Payload:
    try:
        workbook = calamine.CalamineWorkbook.from_filelike(io.BytesIO(raw))
    except (calamine.CalamineError, OSError, ValueError) as error:
        msg = "the workbook could not be opened"
        raise ConversionError(msg) from error

    sections: list[str] = []
    skipped = 0
    clipped = False
    for meta in workbook.sheets_metadata:
        if meta.visible != _VISIBLE:
            skipped += 1
            continue
        sheet = workbook.get_sheet_by_name(meta.name)
        rows = trim(sheet.to_python(skip_empty_area=True, nrows=MAX_ROWS))
        if not rows:
            continue
        clipped = clipped or sheet.total_height > MAX_ROWS
        sections.append(f"## Sheet: {clean(meta.name).text}\n\n{table(rows)}")

    dropped = {"hidden_sheets": skipped} if skipped else {}
    return Payload(
        markdown="\n\n".join(sections),
        pages=len(workbook.sheet_names),
        truncated=clipped,
        dropped=dropped,
    )
