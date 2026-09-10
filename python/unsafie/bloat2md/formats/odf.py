import io
from typing import Any, Final, cast

from odfdo import Document

from unsafie.bloat2md.domain import ConversionError, Payload
from unsafie.bloat2md.markdown import table, trim
from unsafie.bloat2md.sanitize import clean

_HEADING: Final = "h"


def _body(document: Document) -> list[str]:
    blocks: list[str] = []
    for element in cast("list[Any]", document.body.children):
        tag = element.tag.rsplit(":", maxsplit=1)[-1]
        if tag == "table":
            rows = [
                [str(cell.get_value() or cell.text_recursive or "") for cell in row.get_cells()]
                for row in element.get_rows()
            ]
            blocks.append(table(trim(rows)))
            continue
        text = element.text_recursive.strip()
        if not text:
            continue
        blocks.append(f"## {text}" if tag == _HEADING else text)
    return blocks


def convert(raw: bytes) -> Payload:
    try:
        document = Document(io.BytesIO(raw))
        blocks = _body(document)
    except (OSError, ValueError, KeyError, AttributeError) as error:
        msg = "the document could not be read"
        raise ConversionError(msg) from error

    cleaned = clean("\n\n".join(block for block in blocks if block))
    return Payload(markdown=cleaned.text, dropped=cleaned.dropped)
