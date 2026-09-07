import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from unsafie.database import SessionLocal
from unsafie.database.models.api_token import ApiToken, TokenKind
from unsafie.database.repositories.token import TokenRepository
from unsafie.database.repositories.user import UserRepository

logger = logging.getLogger(__name__)

PREFIX = "uns_"

HUMAN_SCOPES = ("chat", "pages", "pool", "github", "automation", "secrets", "accounts", "auth")
MACHINE_SCOPES = ("chat", "pages", "pool", "github", "automation")


def generate() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def digest(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode()).hexdigest()


def mask(raw: str) -> str:
    return f"{raw[:8]}…{raw[-4:]}" if len(raw) > 16 else "…"


async def issue(
    *,
    user_id: int | None,
    bot_id: int | None = None,
    chat_id: int | None = None,
    name: str = "telegram",
    kind: TokenKind = TokenKind.HUMAN,
    scopes: tuple[str, ...] | None = None,
    machine: str | None = None,
    hours: float | None = None,
) -> tuple[ApiToken, str]:
    raw = generate()
    granted = scopes or (HUMAN_SCOPES if kind == TokenKind.HUMAN else MACHINE_SCOPES)
    expires = datetime.now(UTC) + timedelta(hours=hours) if hours else None
    async with SessionLocal() as session:
        if user_id is not None:
            await UserRepository(session).get_or_create(user_id)
        token = await TokenRepository(session).add(
            user_id=user_id,
            bot_id=bot_id,
            chat_id=chat_id,
            name=name,
            token_hash=digest(raw),
            scopes=",".join(granted),
            kind=str(kind),
            machine=machine,
            expires_at=expires,
        )
    return token, raw


async def resolve(raw: str | None) -> ApiToken | None:
    if not raw or not raw.strip():
        return None
    async with SessionLocal() as session:
        repo = TokenRepository(session)
        token = await repo.by_hash(digest(raw))
        if token is None:
            return None
        if token.expires_at is not None and token.expires_at < datetime.now(UTC):
            logger.info("token '%s' of user=%s expired", token.name, token.user_id)
            return None
        await repo.touch(token.id)
        return token


async def listing(user_id: int) -> list[ApiToken]:
    async with SessionLocal() as session:
        return await TokenRepository(session).for_user(user_id)


async def revoke(user_id: int, name: str) -> bool:
    async with SessionLocal() as session:
        return await TokenRepository(session).revoke(user_id, name)


async def revoke_machine(machine: str) -> int:
    async with SessionLocal() as session:
        return await TokenRepository(session).revoke_machine(machine)
