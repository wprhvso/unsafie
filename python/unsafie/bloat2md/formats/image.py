import io
import warnings
from typing import Final

from PIL import Image as Pillow
from PIL import UnidentifiedImageError

from unsafie.bloat2md.config import settings
from unsafie.bloat2md.domain import ConversionError, Image, Payload

_JPEG: Final = "image/jpeg"
_KEEP: Final = frozenset({"image/png", "image/jpeg", "image/webp"})


def normalise(raw: bytes, mime: str) -> Image:
    limits = settings()
    Pillow.MAX_IMAGE_PIXELS = limits.max_image_pixels
    with warnings.catch_warnings():
        warnings.simplefilter("error", Pillow.DecompressionBombWarning)
        try:
            with Pillow.open(io.BytesIO(raw)) as opened:
                width, height = opened.size
                if width * height > limits.max_image_pixels:
                    raise ConversionError("the image has too many pixels")
                longest = max(width, height, 1)
                if longest <= limits.render_edge and mime in _KEEP:
                    return Image(mime=mime, data=raw)
                scale = min(limits.render_edge / longest, 1.0)
                resized = opened.convert("RGB").resize(
                    (max(int(width * scale), 1), max(int(height * scale), 1))
                )
        except (Pillow.DecompressionBombError, Pillow.DecompressionBombWarning):
            raise ConversionError("the image has too many pixels") from None
        except (OSError, UnidentifiedImageError, ValueError):
            raise ConversionError("the image could not be read") from None

    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG", quality=limits.render_quality, optimize=True)
    return Image(mime=_JPEG, data=buffer.getvalue())


def convert(raw: bytes, mime: str) -> Payload:
    return Payload(images=[normalise(raw, mime)], pages=1)
