import io
import zipfile
from pathlib import PurePosixPath
from typing import Final

from unsafie.bloat2md.domain import ConversionError, Payload
from unsafie.bloat2md.limits import audit_archive
from unsafie.bloat2md.markdown import table

_LISTED: Final = 200


def _safe(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def convert(raw: bytes) -> Payload:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            audit_archive(archive)
            members = archive.infolist()
    except (OSError, zipfile.BadZipFile) as error:
        msg = "the archive could not be read"
        raise ConversionError(msg) from error

    rows: list[list[object]] = [["name", "bytes"]]
    unsafe = 0
    for member in members[:_LISTED]:
        if member.is_dir():
            continue
        if not _safe(member.filename):
            unsafe += 1
            continue
        rows.append([member.filename, member.file_size])

    dropped = {"unsafe_names": unsafe} if unsafe else {}
    return Payload(
        markdown=f"## Archive contents\n\n{table(rows)}",
        pages=len(members),
        truncated=len(members) > _LISTED,
        dropped=dropped,
    )
