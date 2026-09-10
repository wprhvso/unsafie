import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class Failure(StrEnum):
    AUTH = "auth"
    LIMIT = "limit"
    OVERLOADED = "overloaded"
    OTHER = "other"


_AUTH = re.compile(
    r"invalid[_ ]token|unauthenticated|unauthorized|permission[_ ]denied|not logged in|"
    r"\b401\b|\b403\b|oauth|refresh",
    re.IGNORECASE,
)
_LIMIT = re.compile(
    r"rate[_ ]limit|\b429\b|resource[_ ]exhausted|quota|exceeded|too many requests",
    re.IGNORECASE,
)
_OVERLOADED = re.compile(
    r"overloaded|\b503\b|\b504\b|\b529\b|unavailable|deadline[_ ]exceeded|timeout",
    re.IGNORECASE,
)

_RPC_KINDS = {
    "UNAUTHENTICATED": Failure.AUTH,
    "PERMISSION_DENIED": Failure.AUTH,
    "RESOURCE_EXHAUSTED": Failure.LIMIT,
    "DEADLINE_EXCEEDED": Failure.OVERLOADED,
    "UNAVAILABLE": Failure.OVERLOADED,
    "ABORTED": Failure.OVERLOADED,
}

_STATUS = {
    401: Failure.AUTH,
    403: Failure.AUTH,
    429: Failure.LIMIT,
    503: Failure.OVERLOADED,
    504: Failure.OVERLOADED,
    529: Failure.OVERLOADED,
}

_LIMIT_BASE = timedelta(minutes=15)
_LIMIT_MAX = timedelta(hours=3)
_OVERLOADED_COOLDOWN = timedelta(minutes=2)


def classify(text: str) -> Failure:
    if _AUTH.search(text):
        return Failure.AUTH
    if _LIMIT.search(text):
        return Failure.LIMIT
    if _OVERLOADED.search(text):
        return Failure.OVERLOADED
    return Failure.OTHER


def classify_api(status: int, kind: str, message: str) -> Failure:
    by_kind = _RPC_KINDS.get(kind)
    if by_kind is not None:
        return by_kind
    by_status = _STATUS.get(status)
    if by_status is not None:
        return by_status
    return classify(message)


def cooldown_for(failures: int, failure: Failure) -> datetime | None:
    now = datetime.now(UTC)
    if failure == Failure.OVERLOADED:
        return now + _OVERLOADED_COOLDOWN
    if failure == Failure.LIMIT:
        delay = _LIMIT_BASE * (2 ** min(max(failures - 1, 0), 4))
        return now + min(delay, _LIMIT_MAX)
    return None


def blames_credential(failure: Failure) -> bool:
    return failure in (Failure.AUTH, Failure.LIMIT, Failure.OVERLOADED)


def mask(secret: str) -> str:
    return f"...{secret[-4:]}" if len(secret) >= 4 else "***"
