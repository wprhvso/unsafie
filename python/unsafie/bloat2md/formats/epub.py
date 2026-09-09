import io
import zipfile
from pathlib import PurePosixPath
from typing import Any, Final

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from unsafie.bloat2md.domain import ConversionError, Payload
from unsafie.bloat2md.formats.html import to_markdown
from unsafie.bloat2md.limits import audit_archive, read_member
from unsafie.bloat2md.sanitize import clean

_CONTAINER: Final = "META-INF/container.xml"
_MEMBER_CAP: Final = 4 * 1024 * 1024
_MAX_DOCUMENTS: Final = 200
_OPF: Final = "{http://www.idpf.org/2007/opf}"
_ROOTFILE: Final = ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"


def _parse(data: bytes) -> Any:
    try:
        return ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True)
    except (DefusedXmlException, ElementTree.ParseError):
        raise ConversionError("the epub metadata could not be parsed") from None


def _spine(archive: zipfile.ZipFile) -> list[str]:
    container = _parse(read_member(archive, _CONTAINER, _MEMBER_CAP))
    rootfile = container.find(_ROOTFILE)
    if rootfile is None:
        raise ConversionError("the epub names no package document")
    package_path = rootfile.get("full-path")
    if package_path is None:
        raise ConversionError("the epub names no package document")

    package = _parse(read_member(archive, package_path, _MEMBER_CAP))
    base = PurePosixPath(package_path).parent
    manifest = {
        item.get("id"): item.get("href") for item in package.iterfind(f"{_OPF}manifest/{_OPF}item")
    }
    names = archive.namelist()

    documents: list[str] = []
    for reference in package.iterfind(f"{_OPF}spine/{_OPF}itemref"):
        href = manifest.get(reference.get("idref"))
        if href is None:
            continue
        candidate = str(base / href) if str(base) != "." else href
        if candidate in names:
            documents.append(candidate)
    return documents


def convert(raw: bytes) -> Payload:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            audit_archive(archive)
            documents = _spine(archive)
            chapters = [
                read_member(archive, name, _MEMBER_CAP) for name in documents[:_MAX_DOCUMENTS]
            ]
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise ConversionError("the epub could not be read") from error

    sections: list[str] = []
    hidden = 0
    for chapter in chapters:
        body, dropped = to_markdown(chapter.decode("utf-8", "replace"))
        hidden += dropped
        if body.strip():
            sections.append(body)

    return Payload(
        markdown=clean("\n\n---\n\n".join(sections)).text,
        pages=len(documents),
        truncated=len(documents) > _MAX_DOCUMENTS,
        dropped={"hidden_nodes": hidden} if hidden else {},
    )
