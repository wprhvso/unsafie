import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class HoldRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def acquire(self, turn_id: UUID, user_id: int, amount: int, lease: int) -> bool:
        row = await self.session.execute(
            text(
                """
                INSERT INTO holds (turn_id, user_id, amount, expires_at)
                SELECT :turn, :user, :amount, now() + (:lease || ' seconds')::interval
                FROM users u
                WHERE u.id = :user
                  AND u.balance - coalesce(
                        (SELECT sum(amount) FROM holds
                         WHERE user_id = u.id AND expires_at > now()), 0) >= :amount
                ON CONFLICT (turn_id) DO UPDATE
                  SET expires_at = now() + (:lease || ' seconds')::interval
                RETURNING turn_id
                """
            ).bindparams(turn=turn_id, user=user_id, amount=amount, lease=str(lease))
        )
        ok = row.scalar() is not None
        await self.session.commit()
        return ok

    async def extend(self, turn_id: UUID, lease: int) -> None:
        await self.session.execute(
            text(
                "UPDATE holds SET expires_at = now() + (:lease || ' seconds')::interval "
                "WHERE turn_id=:turn"
            ).bindparams(lease=str(lease), turn=turn_id)
        )
        await self.session.commit()

    async def release(self, turn_id: UUID) -> None:
        await self.session.execute(
            text("DELETE FROM holds WHERE turn_id=:turn").bindparams(turn=turn_id)
        )
        await self.session.commit()

    async def held(self, user_id: int) -> int:
        value = await self.session.scalar(
            text(
                "SELECT coalesce(sum(amount), 0) FROM holds "
                "WHERE user_id=:user AND expires_at > now()"
            ).bindparams(user=user_id)
        )
        return int(value or 0)
