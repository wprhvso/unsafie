from collections.abc import Callable
from typing import Final

from unsafie.bloat2md.config import settings
from unsafie.bloat2md.domain import ConversionError, Kind, Payload, UnsupportedFile
from unsafie.bloat2md.formats import archive, epub, html, image, legacy, odf, ooxml, pdf
from unsafie.bloat2md.formats import spreadsheet as sheets
from unsafie.bloat2md.formats import text as plain
from unsafie.bloat2md.sanitize import clip
from unsafie.bloat2md.sniff import detect, image_mime

_BY_KIND: Final[dict[Kind, Callable[[bytes], Payload]]] = {
    Kind.PDF: pdf.convert,
    Kind.DOCX: ooxml.docx,
    Kind.PPTX: ooxml.pptx,
    Kind.XLSX: sheets.convert,
    Kind.ODS: sheets.convert,
    Kind.ODT: odf.convert,
    Kind.ODP: odf.convert,
    Kind.RTF: plain.rtf,
    Kind.HTML: html.convert,
    Kind.EPUB: epub.convert,
    Kind.CSV: plain.delimited,
    Kind.JSON: plain.structured,
    Kind.XML: plain.xml,
    Kind.IPYNB: plain.notebook,
    Kind.YAML: plain.plain,
    Kind.TEXT: plain.plain,
    Kind.ARCHIVE: archive.convert,
    Kind.LEGACY: legacy.convert,
}


def _fallback(kind: Kind, raw: bytes, error: ConversionError, name: str = "") -> Payload:
    if kind in {Kind.PPTX, Kind.ODT, Kind.ODP, Kind.RTF, Kind.DOCX} and legacy.available():
        return legacy.convert(raw, name or "input.bin")
    raise error


def convert(raw: bytes, name: str) -> tuple[Kind, Payload]:
    kind = detect(raw, name)
    if kind is None:
        msg = "the file is not a document bloat2md can read"
        raise UnsupportedFile(msg)

    if kind is Kind.IMAGE:
        mime = image_mime(raw) or "image/png"
        return kind, image.convert(raw, mime)

    handler = _BY_KIND.get(kind)
    if handler is None:
        msg = "the file is not a document bloat2md can read"
        raise UnsupportedFile(msg)

    try:
        if kind is Kind.LEGACY:
            payload = legacy.convert(raw, name)
        else:
            payload = handler(raw)
    except ConversionError as error:
        payload = _fallback(kind, raw, error, name)

    markdown, truncated = clip(payload.markdown, settings().max_markdown_chars)
    return kind, Payload(
        markdown=markdown,
        images=payload.images[: settings().max_render_pages],
        pages=payload.pages,
        truncated=payload.truncated or truncated,
        dropped=payload.dropped,
    )
