import io
from collections.abc import Iterator
from typing import Final, cast

import pypdfium2 as pdfium

from unsafie.bloat2md.config import settings
from unsafie.bloat2md.domain import ConversionError, Image, Payload
from unsafie.bloat2md.markdown import cell
from unsafie.bloat2md.sanitize import clean

MIN_FONT_SIZE: Final = 2.0
MIN_PAGE_CHARS: Final = 24
MIN_HIDDEN_CHARS: Final = 8
_JPEG: Final = "image/jpeg"


def _hidden_text(page: pdfium.PdfPage, textpage: pdfium.PdfTextPage) -> Iterator[str]:
    width, height = page.get_size()
    cropbox = page.get_cropbox() or (0.0, 0.0, width, height)
    for obj in page.get_objects(textpage=textpage):
        if not isinstance(obj, pdfium.PdfTextObj):
            continue
        mode = pdfium.raw.FPDFTextObj_GetTextRenderMode(obj.raw)
        left, bottom, right, top = obj.get_bounds()
        if (
            mode == pdfium.raw.FPDF_TEXTRENDERMODE_INVISIBLE
            or obj.get_font_size() < MIN_FONT_SIZE
            or right <= cropbox[0]
            or left >= cropbox[2]
            or top <= cropbox[1]
            or bottom >= cropbox[3]
        ):
            yield obj.extract()


def _overlaps(line: str, hidden: str) -> bool:
    s_line = line.strip()
    s_hidden = hidden.strip()
    return len(s_line) >= MIN_HIDDEN_CHARS and s_line == s_hidden


def _visible_text(page: pdfium.PdfPage) -> tuple[str, int]:
    textpage = page.get_textpage()
    try:
        text = textpage.get_text_bounded().replace("\r\n", "\n")
        hidden = [
            candidate
            for span in _hidden_text(page, textpage)
            if len(candidate := span.strip()) >= MIN_HIDDEN_CHARS
        ]
    finally:
        textpage.close()

    if not hidden:
        return text, 0

    kept: list[str] = []
    dropped = 0
    for line in text.split("\n"):
        if any(_overlaps(line.strip(), span) for span in hidden):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept), dropped


def _render(page: pdfium.PdfPage) -> bytes:
    limits = settings()
    width, height = page.get_size()
    scale = min(limits.render_edge / max(width, height, 1), 4.0)
    bitmap = page.render(scale=cast("int", scale))
    try:
        image = bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=limits.render_quality, optimize=True)
    return buffer.getvalue()


def convert(raw: bytes) -> Payload:
    limits = settings()
    stream = io.BytesIO(raw)
    try:
        document = pdfium.PdfDocument(stream)
    except pdfium.PdfiumError as error:
        raise ConversionError("the pdf could not be opened") from error

    sections: list[str] = []
    images: list[Image] = []
    hidden = 0
    try:
        total = len(document)
        for number in range(min(total, limits.max_pages)):
            page = document[number]
            try:
                text, dropped = _visible_text(page)
                hidden += dropped
                body = clean(text).text
                if len(cell(body).strip()) >= MIN_PAGE_CHARS:
                    sections.append(f"## Page {number + 1}\n\n{body}")
                elif len(images) < limits.max_render_pages:
                    sections.append(f"## Page {number + 1}\n\n[page image]")
                    images.append(Image(mime=_JPEG, data=_render(page)))
            finally:
                page.close()
    finally:
        document.close()

    dropped_counts = {"hidden_spans": hidden} if hidden else {}
    return Payload(
        markdown="\n\n".join(sections),
        images=images,
        pages=total,
        truncated=total > limits.max_pages,
        dropped=dropped_counts,
    )
