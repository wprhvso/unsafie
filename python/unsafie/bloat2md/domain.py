from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    ODT = "odt"
    ODS = "ods"
    ODP = "odp"
    RTF = "rtf"
    LEGACY = "legacy"
    HTML = "html"
    EPUB = "epub"
    CSV = "csv"
    JSON = "json"
    YAML = "yaml"
    XML = "xml"
    IPYNB = "ipynb"
    TEXT = "text"
    IMAGE = "image"
    ARCHIVE = "archive"


@dataclass(frozen=True, slots=True)
class Image:
    mime: str
    data: bytes


@dataclass(frozen=True, slots=True)
class Payload:
    markdown: str = ""
    images: list[Image] = field(default_factory=list)
    pages: int = 0
    truncated: bool = False
    dropped: dict[str, int] = field(default_factory=dict)


class ConversionError(Exception):
    pass


class UnsupportedFile(ConversionError):
    pass
