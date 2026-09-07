import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from unsafie.database.models.credential import CredentialKind


class Failure(StrEnum):
    AUTH = "auth"
    LIMIT = "limit"
    OVERLOADED = "overloaded"
    OTHER = "other"


_AUTH = re.compile(
    r"invalid api key|authentication[_ ]error|permission[_ ]error|not logged in|\b401\b|\b403\b|"
    r"unauthorized|invalid (?:bearer |oauth )?token|token (?:has )?(?:expired|been revoked)|"
    r"please (?:run )?/login|oauth token (?:is )?(?:invalid|expired)|invalid x-api-key",
    re.I,
)
_LIMIT = re.compile(
    r"rate[_ ]limit|\b429\b|usage limit|hit your limit|limit reached|"
    r"credit balance|insufficient (?:credits|funds|quota)|quota|billing|"
    r"out of (?:extra )?usage|resets? (?:at|in) ",
    re.I,
)
_OVERLOADED = re.compile(r"overloaded|\b529\b|\b503\b|service unavailable|timed? ?out", re.I)

_KINDS = {
    "authentication_error": Failure.AUTH,
    "permission_error": Failure.AUTH,
    "rate_limit_error": Failure.LIMIT,
    "billing_error": Failure.LIMIT,
    "overloaded_error": Failure.OVERLOADED,
    "timeout_error": Failure.OVERLOADED,
}
_STATUS = {
    401: Failure.AUTH,
    403: Failure.AUTH,
    402: Failure.LIMIT,
    429: Failure.LIMIT,
    503: Failure.OVERLOADED,
    504: Failure.OVERLOADED,
    529: Failure.OVERLOADED,
}

_LIMIT_BASE = {
    CredentialKind.OAUTH: timedelta(minutes=30),
    CredentialKind.API_KEY: timedelta(minutes=5),
}
_LIMIT_MAX = {CredentialKind.OAUTH: timedelta(hours=5), CredentialKind.API_KEY: timedelta(hours=1)}
_OVERLOADED_COOLDOWN = timedelta(minutes=2)


def classify(text: str) -> Failure:
    if _AUTH.search(text):
        return Failure.AUTH
    if _OVERLOADED.search(text):
        return Failure.OVERLOADED
    if _LIMIT.search(text):
        return Failure.LIMIT
    return Failure.OTHER


def classify_api(status: int, kind: str, message: str) -> Failure:
    by_kind = _KINDS.get(kind)
    if by_kind is not None:
        return by_kind
    by_status = _STATUS.get(status)
    if by_status is not None:
        return by_status
    return classify(message)


def cooldown_for(kind: str, failures: int, failure: Failure) -> datetime | None:
    now = datetime.now(UTC)
    if failure == Failure.OVERLOADED:
        return now + _OVERLOADED_COOLDOWN
    if failure == Failure.LIMIT:
        key = CredentialKind(kind)
        delay = _LIMIT_BASE[key] * (2 ** min(max(failures - 1, 0), 4))
        return now + min(delay, _LIMIT_MAX[key])
    return None


def blames_credential(failure: Failure) -> bool:
    return failure in (Failure.AUTH, Failure.LIMIT, Failure.OVERLOADED)


def mask(secret: str) -> str:
    return f"{secret[:10]}…{secret[-4:]}" if len(secret) > 18 else "***"
