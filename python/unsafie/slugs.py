import re
import secrets
import string

SLUG_ALPHABET = string.ascii_uppercase
SLUG_LENGTH = 12
SLUG_PATTERN = re.compile(f"[{SLUG_ALPHABET}]{{{SLUG_LENGTH}}}")


def generate_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


def is_slug(value: str) -> bool:
    return SLUG_PATTERN.fullmatch(value) is not None
