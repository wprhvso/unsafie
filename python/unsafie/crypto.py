import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from unsafie.settings import settings

logger = logging.getLogger(__name__)


def _derive_fernet_key(secret: str) -> bytes:
    derived = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(derived)


def _fernet() -> Fernet:
    key_material = settings.secret_key or settings.admin_token or settings.instance_id
    fernet_key = _derive_fernet_key(key_material)
    return Fernet(fernet_key)


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    if not plaintext:
        return ""
    try:
        f = _fernet()
        return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("encryption failure: %s", e)
        raise


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    if not ciphertext:
        return ""
    try:
        f = _fernet()
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ciphertext
    except Exception as e:
        logger.warning("decryption fallback to raw value: %s", e)
        return ciphertext
