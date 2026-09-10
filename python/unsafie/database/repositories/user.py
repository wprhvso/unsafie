import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.user import User

logger = logging.getLogger(__name__)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_or_create(self, user_id: int) -> User:
        user = await self.get(user_id)
        if user is None:
            user = User(id=user_id)
            self.session.add(user)
            await self.session.commit()
            logger.info("user=%s row created", user_id)
        return user

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[User], int]:
        total = await self.session.scalar(select(func.count()).select_from(User)) or 0
        rows = await self.session.scalars(
            select(User).order_by(User.id).offset(offset).limit(limit),
        )
        return list(rows), int(total)

    async def set_locale(self, user_id: int, locale: str | None) -> User:
        user = await self.get_or_create(user_id)
        user.locale = locale
        await self.session.commit()
        return user

    async def set_effort(self, user_id: int, effort: str | None) -> User:
        user = await self.get_or_create(user_id)
        user.effort = effort
        await self.session.commit()
        return user
