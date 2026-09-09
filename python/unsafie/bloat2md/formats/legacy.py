import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

from unsafie.bloat2md.config import settings
from unsafie.bloat2md.domain import ConversionError, Payload, UnsupportedFile
from unsafie.bloat2md.formats import pdf

SOFFICE: Final = "soffice"
_FILTER: Final = "pdf:writer_pdf_Export"


def available() -> bool:
    return settings().libreoffice and shutil.which(SOFFICE) is not None


def _run(source: Path, outdir: Path, profile: Path, timeout: float) -> None:
    binary = shutil.which(SOFFICE)
    if binary is None:
        raise UnsupportedFile("libreoffice is not installed")
    completed = subprocess.run(
        [
            binary,
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nologo",
            "--convert-to",
            _FILTER,
            "--outdir",
            str(outdir),
            str(source),
        ],
        capture_output=True,
        timeout=timeout,
        check=False,
        env={"HOME": str(profile), "PATH": "/usr/bin:/bin", "TMPDIR": str(profile)},
    )
    if completed.returncode != 0:
        raise ConversionError("libreoffice refused the document")


def convert(raw: bytes) -> Payload:
    if not available():
        raise UnsupportedFile("this format needs libreoffice")

    with tempfile.TemporaryDirectory(prefix="bloat2md-") as workdir:
        root = Path(workdir)
        profile = root / "profile"
        outdir = root / "out"
        profile.mkdir()
        outdir.mkdir()
        source = root / "input.bin"
        _ = source.write_bytes(raw)

        try:
            _run(source, outdir, profile, settings().timeout)
        except subprocess.TimeoutExpired as error:
            raise ConversionError("libreoffice ran out of time") from error
        except OSError as error:
            raise ConversionError("libreoffice could not be started") from error

        produced = sorted(outdir.glob("*.pdf"))
        if not produced:
            raise ConversionError("libreoffice produced nothing")
        return pdf.convert(produced[0].read_bytes())
