import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from aiogram import Bot
from fastapi import Depends, Header, HTTPException

from unsafie import tokens
from unsafie.database import SessionLocal
from unsafie.database.models.api_token import ApiToken
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository
from unsafie.telegram import bots

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Caller:
    token: ApiToken

    @property
    def user_id(self) -> int:
        if self.token.user_id is None:
            raise HTTPException(403, "this token belongs to no user yet")
        return self.token.user_id

    @property
    def bot_id(self) -> int | None:
        return self.token.bot_id

    @property
    def chat_id(self) -> int | None:
        return self.token.chat_id

    @property
    def machine(self) -> str | None:
        return self.token.machine

    @property
    def prefix(self) -> str:
        return f"cli user={self.user_id} token={self.token.name}"

    def allows(self, scope: str) -> bool:
        return scope in self.token.scope_set

    def chat(self, override: int | None = None) -> int:
        if self.chat_id is not None:
            if override is not None and override != self.chat_id:
                raise HTTPException(403, "cross-chat access is forbidden for this token")
            return self.chat_id
        chat_id = override
        if chat_id is None:
            raise HTTPException(400, "no chat: pass chat_id or use a token bound to a chat")
        return chat_id

    async def ensure_admin(self, target_chat: int) -> None:
        if target_chat == self.user_id:
            return
        bot = await self.bot()
        try:
            member = await bot.get_chat_member(target_chat, self.user_id)
            if member.status not in ("creator", "administrator"):
                raise HTTPException(403, "admin privileges required in the target chat")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(403, f"cannot verify admin status: {e}") from None

    async def target_chat(self, override: int | None = None) -> int:
        if self.chat_id is not None:
            if override is not None and override != self.chat_id:
                raise HTTPException(403, "cross-chat access is forbidden for this token")
            return self.chat_id
        target = override
        if target is None:
            raise HTTPException(400, "no chat: pass chat_id or use a token bound to a chat")
        if target == self.user_id:
            return target
        bot = await self.bot()
        try:
            member = await bot.get_chat_member(target, self.user_id)
            if member.status in ("left", "kicked"):
                msg = "user is not a member of the target chat"
                raise HTTPException(403, msg)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(403, f"cannot access target chat: {e}") from None
        return target

    async def bot(self) -> Bot:
        if self.bot_id is None:
            raise HTTPException(400, "this token is not bound to a bot")
        opened = await bots.bot_for(self.bot_id)
        if opened is None:
            raise HTTPException(503, "the bot behind this token is gone")
        return opened

    async def turn(self, turn_id: str | None) -> Turn | None:
        if not turn_id:
            return None
        try:
            parsed = UUID(turn_id)
        except ValueError:
            return None
        async with SessionLocal() as session:
            turn = await TurnRepository(session).get(parsed)
        if turn is None or turn.user_id != self.user_id:
            return None
        return turn


async def _caller(
    authorization: Annotated[str | None, Header()] = None,
    x_unsafie_token: Annotated[str | None, Header()] = None,
) -> Caller:
    raw = x_unsafie_token
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    token = await tokens.resolve(raw)
    if token is None:
        raise HTTPException(401, "unknown, expired or revoked token")
    return Caller(token)


Who = Annotated[Caller, Depends(_caller)]


def scoped(scope: str):
    async def check(who: Who) -> Caller:
        if not who.allows(scope):
            raise HTTPException(403, f"this token has no '{scope}' scope")
        return who

    return Depends(check)


Chat = Annotated[Caller, scoped("chat")]
Pages = Annotated[Caller, scoped("pages")]
Pool = Annotated[Caller, scoped("pool")]
Github = Annotated[Caller, scoped("github")]
Automation = Annotated[Caller, scoped("automation")]
Secrets = Annotated[Caller, scoped("secrets")]
Accounts = Annotated[Caller, scoped("accounts")]
