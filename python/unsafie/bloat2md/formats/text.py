import csv
import io
import json
from typing import Final

from charset_normalizer import from_bytes
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from striprtf.striprtf import rtf_to_text

from unsafie.bloat2md.domain import ConversionError, Payload
from unsafie.bloat2md.markdown import table, trim
from unsafie.bloat2md.sanitize import clean

SNIFF_BYTES: Final = 16384
MAX_CSV_ROWS: Final = 500
_DELIMITERS: Final = ",;\t|"


def decode(raw: bytes) -> str:
    best = from_bytes(raw).best()
    if best is None:
        msg = "the text could not be decoded"
        raise ConversionError(msg)
    return str(best)


def plain(raw: bytes) -> Payload:
    cleaned = clean(decode(raw))
    return Payload(markdown=cleaned.text, dropped=cleaned.dropped)


def rtf(raw: bytes) -> Payload:
    try:
        text = rtf_to_text(decode(raw), errors="ignore")
    except (ValueError, IndexError, KeyError) as error:
        msg = "the rtf could not be read"
        raise ConversionError(msg) from error
    cleaned = clean(text)
    return Payload(markdown=cleaned.text, dropped=cleaned.dropped)


def delimited(raw: bytes) -> Payload:
    text = decode(raw)
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2147483647)
    try:
        dialect = csv.Sniffer().sniff(text[:SNIFF_BYTES], delimiters=_DELIMITERS)
    except csv.Error:
        dialect = csv.excel
    try:
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error as e:
        raise ConversionError(f"csv parsing failed: {e}") from e
    kept = trim(rows[:MAX_CSV_ROWS])
    return Payload(markdown=table(kept), truncated=len(rows) > MAX_CSV_ROWS)


def structured(raw: bytes) -> Payload:
    text = decode(raw)
    try:
        parsed = json.loads(text)
    except ValueError as error:
        msg = "the json could not be parsed"
        raise ConversionError(msg) from error
    body = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=False)
    return Payload(markdown=clean(body).text)


def xml(raw: bytes) -> Payload:
    try:
        root = ElementTree.fromstring(raw, forbid_dtd=True, forbid_entities=True)
    except (DefusedXmlException, ElementTree.ParseError):
        msg = "the xml could not be parsed"
        raise ConversionError(msg) from None
    body = ElementTree.tostring(root, encoding="unicode")
    return Payload(markdown=clean(body).text)


def notebook(raw: bytes) -> Payload:
    try:
        parsed = json.loads(decode(raw))
    except ValueError as error:
        msg = "the notebook could not be parsed"
        raise ConversionError(msg) from error
    if not isinstance(parsed, dict):
        msg = "the notebook is not an object"
        raise ConversionError(msg)

    blocks: list[str] = []
    cells = parsed.get("cells")
    for cell in cells if isinstance(cells, list) else []:
        if not isinstance(cell, dict):
            continue
        source = cell.get("source")
        body = "".join(source) if isinstance(source, list) else str(source or "")
        if not body.strip():
            continue
        if cell.get("cell_type") == "markdown":
            blocks.append(body.strip())
        else:
            blocks.append(f"```python\n{body.strip()}\n```")

    return Payload(markdown=clean("\n\n".join(blocks)).text, pages=len(blocks))
