import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.transaction import Transaction
from unsafie.database.models.user import User

logger = logging.getLogger(__name__)


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_or_create(self, user_id: int) -> User:
        user = await self.get(user_id)
        if user is None:
            user = User(id=user_id, balance=0)
            self.session.add(user)
            await self.session.commit()
            logger.info("user=%s row created", user_id)
        return user

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[User], int]:
        total = await self.session.scalar(select(func.count()).select_from(User)) or 0
        rows = await self.session.scalars(
            select(User).order_by(User.id).offset(offset).limit(limit)
        )
        return list(rows), int(total)

    async def apply(self, user_id: int, amount: int, kind: str) -> User:
        await self.get_or_create(user_id)
        balance = await self.session.scalar(
            text("UPDATE users SET balance = balance + :a WHERE id = :id RETURNING balance")
            .bindparams(a=amount, id=user_id)
        )
        self.session.add(Transaction(user_id=user_id, amount=amount, kind=kind))
        await self.session.commit()
        logger.info("user=%s %s amount=%s balance=%s", user_id, kind, amount, balance)
        return await self.get(user_id)

    async def deposit(self, user_id: int, amount: int) -> User:
        return await self.apply(user_id, amount, "deposit")

    async def charge(self, user_id: int, amount: int) -> User:
        return await self.apply(user_id, -amount, "usage")

    async def set_budget(self, user_id: int, budget: int) -> User:
        user = await self.get_or_create(user_id)
        user.budget = budget
        await self.session.commit()
        return user

    async def set_locale(self, user_id: int, locale: str | None) -> User:
        user = await self.get_or_create(user_id)
        user.locale = locale
        await self.session.commit()
        return user

    async def set_model(self, user_id: int, model: str | None) -> User:
        user = await self.get_or_create(user_id)
        user.model = model
        await self.session.commit()
        return user

    async def set_effort(self, user_id: int, effort: str | None) -> User:
        user = await self.get_or_create(user_id)
        user.effort = effort
        await self.session.commit()
        return user

    async def transactions(self, user_id: int, limit: int = 50) -> list[Transaction]:
        rows = await self.session.scalars(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.id.desc())
            .limit(limit)
        )
        return list(rows)
