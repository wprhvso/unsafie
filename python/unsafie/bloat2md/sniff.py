import io
import zipfile
from pathlib import PurePosixPath
from typing import Final

from unsafie.bloat2md.domain import Kind

_OOXML_PARTS: Final = (
    ("word/document.xml", Kind.DOCX),
    ("xl/workbook.xml", Kind.XLSX),
    ("ppt/presentation.xml", Kind.PPTX),
)

_ODF_MIMES: Final = {
    "application/vnd.oasis.opendocument.text": Kind.ODT,
    "application/vnd.oasis.opendocument.text-template": Kind.ODT,
    "application/vnd.oasis.opendocument.spreadsheet": Kind.ODS,
    "application/vnd.oasis.opendocument.spreadsheet-template": Kind.ODS,
    "application/vnd.oasis.opendocument.presentation": Kind.ODP,
    "application/vnd.oasis.opendocument.presentation-template": Kind.ODP,
    "application/vnd.oasis.opendocument.graphics": Kind.ODP,
    "application/epub+zip": Kind.EPUB,
}

_IMAGE_MAGIC: Final = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

_TEXT_SUFFIXES: Final = {
    "csv": Kind.CSV,
    "tsv": Kind.CSV,
    "json": Kind.JSON,
    "ipynb": Kind.IPYNB,
    "yaml": Kind.YAML,
    "yml": Kind.YAML,
    "xml": Kind.XML,
    "html": Kind.HTML,
    "htm": Kind.HTML,
    "xhtml": Kind.HTML,
}

_HTML_MARKERS: Final = (b"<!doctype html", b"<html", b"<head", b"<body")


def image_mime(raw: bytes) -> str | None:
    for magic, mime in _IMAGE_MAGIC:
        if raw.startswith(magic):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[4:12] in {b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypavif"}:
        return "image/heic"
    return None


def _zip_kind(raw: bytes) -> Kind:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
            if "mimetype" in names:
                declared = archive.read("mimetype")[:128].decode("ascii", "replace")
                known = _ODF_MIMES.get(declared.strip())
                if known is not None:
                    return known
            for part, kind in _OOXML_PARTS:
                if part in names:
                    return kind
    except (OSError, zipfile.BadZipFile):
        return Kind.ARCHIVE
    return Kind.ARCHIVE


def _text_kind(raw: bytes, name: str) -> Kind:
    stripped = raw.lstrip()[:512].lower()
    if any(stripped.startswith(marker) for marker in _HTML_MARKERS):
        return Kind.HTML
    if stripped.startswith(b"<?xml"):
        return Kind.XML
    suffix = PurePosixPath(name).suffix.removeprefix(".").lower()
    hinted = _TEXT_SUFFIXES.get(suffix)
    if hinted is not None:
        return hinted
    if stripped.startswith((b"{", b"[")):
        return Kind.JSON
    return Kind.TEXT


def detect(raw: bytes, name: str) -> Kind | None:
    if not raw:
        return None
    if raw.startswith(b"%PDF-"):
        return Kind.PDF
    if raw.startswith(b"{\\rtf"):
        return Kind.RTF
    if raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return Kind.LEGACY
    if image_mime(raw) is not None:
        return Kind.IMAGE
    if raw.startswith(b"PK\x03\x04"):
        return _zip_kind(raw)
    if b"\x00" in raw[:8192]:
        return None
    return _text_kind(raw, name)
