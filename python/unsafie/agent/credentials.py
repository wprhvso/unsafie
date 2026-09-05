import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from unsafie.database.models.credential import AnthropicCredential, CredentialKind


class Failure(StrEnum):
    AUTH = "auth"
    LIMIT = "limit"
    OVERLOADED = "overloaded"
    MISSING_SESSION = "missing_session"
    OTHER = "other"


_AUTH = re.compile(
    r"invalid api key|authentication[_ ]error|not logged in|\b401\b|unauthorized|"
    r"invalid (?:bearer |oauth )?token|token (?:has )?(?:expired|been revoked)|"
    r"please (?:run )?/login|oauth token (?:is )?(?:invalid|expired)|invalid x-api-key",
    re.I,
)
_LIMIT = re.compile(
    r"rate[_ ]limit|\b429\b|usage limit|hit your limit|limit reached|"
    r"credit balance|insufficient (?:credits|funds|quota)|quota|billing|"
    r"out of (?:extra )?usage|resets? (?:at|in) ",
    re.I,
)
_OVERLOADED = re.compile(r"overloaded|\b529\b|\b503\b|service unavailable", re.I)
_MISSING = re.compile(r"no conversation found|session (?:not found|does not exist)", re.I)

_LIMIT_BASE = {
    CredentialKind.OAUTH: timedelta(minutes=30),
    CredentialKind.API_KEY: timedelta(minutes=5),
}
_LIMIT_MAX = {CredentialKind.OAUTH: timedelta(hours=5), CredentialKind.API_KEY: timedelta(hours=1)}
_OVERLOADED_COOLDOWN = timedelta(minutes=2)


def env_for(credential: AnthropicCredential) -> dict[str, str]:
    if credential.kind == CredentialKind.OAUTH:
        return {"CLAUDE_CODE_OAUTH_TOKEN": credential.secret, "ANTHROPIC_API_KEY": ""}
    return {"ANTHROPIC_API_KEY": credential.secret, "CLAUDE_CODE_OAUTH_TOKEN": ""}


def classify(text: str) -> Failure:
    if _MISSING.search(text):
        return Failure.MISSING_SESSION
    if _AUTH.search(text):
        return Failure.AUTH
    if _OVERLOADED.search(text):
        return Failure.OVERLOADED
    if _LIMIT.search(text):
        return Failure.LIMIT
    return Failure.OTHER


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
