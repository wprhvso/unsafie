import zipfile
from typing import Final

from unsafie.bloat2md.config import settings
from unsafie.bloat2md.domain import ConversionError

_MIN_COMPRESSED: Final = 512


def audit_archive(archive: zipfile.ZipFile) -> None:
    limits = settings()
    members = archive.infolist()
    if len(members) > limits.max_archive_members:
        msg = "archive holds too many members"
        raise ConversionError(msg)

    total = 0
    for member in members:
        total += member.file_size
        if total > limits.max_archive_bytes:
            msg = "archive expands past the budget"
            raise ConversionError(msg)
        if (
            member.compress_size >= _MIN_COMPRESSED
            and member.file_size > member.compress_size * limits.max_archive_ratio
        ):
            msg = "archive member expands past the ratio"
            raise ConversionError(msg)


def read_member(archive: zipfile.ZipFile, name: str, cap: int) -> bytes:
    with archive.open(name) as handle:
        data = handle.read(cap + 1)
    if len(data) > cap:
        msg = "archive member is larger than the budget"
        raise ConversionError(msg)
    return data
