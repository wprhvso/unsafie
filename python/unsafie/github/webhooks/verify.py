import hashlib
import hmac
from unsafie.log import get_logger

logger = get_logger(__name__)

PREFIX = "sha256="


def signature(secret: str, body: bytes) -> str:
    return PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def valid(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith(PREFIX):
        return False
    return hmac.compare_digest(signature(secret, body), header)
