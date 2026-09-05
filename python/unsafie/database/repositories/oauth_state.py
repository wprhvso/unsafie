import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.oauth_state import OAuthState

TTL = timedelta(minutes=10)


class OAuthStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def issue(self, user_id: int, bot_id: int, chat_id: int) -> str:
        state = secrets.token_urlsafe(32)
        self.session.add(
            OAuthState(
                state=state,
                user_id=user_id,
                bot_id=bot_id,
                chat_id=chat_id,
                expires_at=datetime.now(UTC) + TTL,
            )
        )
        await self.session.commit()
        return state

    async def consume(self, state: str) -> OAuthState | None:
        row = await self.session.get(OAuthState, state)
        if row is None:
            return None
        await self.session.delete(row)
        await self.session.commit()
        if row.expires_at < datetime.now(UTC):
            return None
        return row

    async def purge(self) -> int:
        res = await self.session.execute(
            delete(OAuthState).where(OAuthState.expires_at < datetime.now(UTC))
        )
        await self.session.commit()
        return res.rowcount or 0
