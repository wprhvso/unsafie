import base64
import re

IMAGE_LIMIT = 5 * 1024 * 1024
DOWNLOAD_LIMIT = 20 * 1024 * 1024

VIEWABLE = {"image/jpeg", "image/png", "image/gif", "image/webp"}

_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
    (b"Rar!", "application/x-rar"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"\x00\x00\x00\x1cftyp", "video/mp4"),
    (b"\x00\x00\x00\x18ftyp", "video/mp4"),
    (b"\x00\x00\x00\x20ftyp", "video/mp4"),
    (b"OggS", "audio/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"fLaC", "audio/flac"),
    (b"\x7fELF", "application/x-elf"),
    (b"SQLite format 3", "application/x-sqlite3"),
]

_EXT = {
    "svg": "image/svg+xml",
    "json": "application/json",
    "md": "text/markdown",
    "txt": "text/plain",
    "csv": "text/csv",
    "py": "text/x-python",
    "js": "text/javascript",
    "ts": "text/typescript",
    "html": "text/html",
    "xml": "text/xml",
    "yaml": "text/yaml",
    "yml": "text/yaml",
    "toml": "text/toml",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "cp1251", "latin-1")

IMAGE_URL_RE = re.compile(
    r"!\[[^\]]*\]\((\S+?)(?:\s+\"[^\"]*\")?\)"
    r"|<img[^>]+src=[\"']([^\"']+)[\"']"
    r"|(https?://(?:github\.com/user-attachments/assets/|user-images\.githubusercontent\.com/|"
    r"private-user-images\.githubusercontent\.com/)[^\s)>\"']+)",
    re.IGNORECASE,
)
ATTACHMENT_URL_RE = re.compile(
    r"\[[^\]]*\]\((https?://github\.com/user-attachments/files/[^\s)]+)\)"
    r"|(https?://github\.com/user-attachments/files/[^\s)>\"']+)"
)


def sniff_mime(data: bytes, name: str | None = None) -> str:
    head = data[:32]
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if name and "." in name:
        ext = name.rsplit(".", 1)[-1].lower()
        if ext in _EXT:
            return _EXT[ext]
    if b"\x00" in data[:8192]:
        return "application/octet-stream"
    try:
        data.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def decode_text(data: bytes) -> tuple[str, str] | None:
    if b"\x00" in data[:8192] and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        return None
    for enc in _ENCODINGS:
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if enc == "latin-1" and sum(ch < " " and ch not in "\t\n\r" for ch in text[:4096]) > 8:
            return None
        return text, enc
    return None


def is_text(data: bytes | None) -> bool:
    if data is None:
        return True
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def number_lines(text: str, start: int | None, end: int | None, limit: int) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    s = max(1, int(start or 1))
    e = int(end or len(lines))
    numbered = "".join(f"{i}\t{line}" for i, line in enumerate(lines[s - 1 : e], s))
    if len(numbered) > limit:
        numbered = numbered[:limit] + "\n…(truncated, read by start_line/end_line ranges)"
    return numbered, len(lines)


def image_block(data: bytes, mime: str) -> dict:
    return {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": mime}


def image_result(data: bytes, mime: str, note: str | None = None) -> dict:
    content: list[dict] = []
    if note:
        content.append({"type": "text", "text": note})
    content.append(image_block(data, mime))
    return {"content": content}


def image_problem(data: bytes, mime: str) -> str | None:
    if mime == "image/svg+xml":
        return "SVG is text, read it as a file"
    if not mime.startswith("image/"):
        return f"not an image ({mime}, {len(data)} bytes)"
    if mime not in VIEWABLE:
        return f"format {mime} is not viewable, supported: jpeg/png/gif/webp"
    if len(data) > IMAGE_LIMIT:
        return f"image is {len(data)} bytes, limit is {IMAGE_LIMIT}; ask for a smaller one"
    return None


def find_images(text: str | None) -> list[str]:
    out: list[str] = []
    for m in IMAGE_URL_RE.finditer(text or ""):
        url = next(g for g in m.groups() if g)
        if url not in out:
            out.append(url)
    return out


def find_attachments(text: str | None) -> list[str]:
    out: list[str] = []
    for m in ATTACHMENT_URL_RE.finditer(text or ""):
        url = next(g for g in m.groups() if g)
        if url not in out:
            out.append(url)
    return out


def human_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"
