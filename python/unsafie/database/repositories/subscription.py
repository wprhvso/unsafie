import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.repo import Repo
from unsafie.database.models.subscription import GithubSubscription

logger = logging.getLogger(__name__)


class SubscriptionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def for_chat(self, bot_id: int, chat_id: int) -> list[tuple[GithubSubscription, Repo]]:
        rows = await self.session.execute(
            select(GithubSubscription, Repo)
            .join(Repo, Repo.id == GithubSubscription.repo_id)
            .where(GithubSubscription.bot_id == bot_id, GithubSubscription.chat_id == chat_id)
            .order_by(GithubSubscription.id)
        )
        return [(s, r) for s, r in rows]

    async def for_repo(self, repo_id: int) -> list[GithubSubscription]:
        return list(
            await self.session.scalars(
                select(GithubSubscription)
                .where(GithubSubscription.repo_id == repo_id)
                .order_by(GithubSubscription.id)
            )
        )

    async def get(self, sub_id: int) -> GithubSubscription | None:
        return await self.session.get(GithubSubscription, sub_id)

    async def add(
        self, bot_id: int, chat_id: int, user_id: int, repo_id: int, kind: str, filters: dict
    ) -> GithubSubscription:
        sub = GithubSubscription(
            bot_id=bot_id,
            chat_id=chat_id,
            user_id=user_id,
            repo_id=repo_id,
            kind=kind,
            filters=filters,
        )
        self.session.add(sub)
        await self.session.commit()
        logger.info(
            "bot=%s chat=%s repo_id=%s sub=%s kind=%s added", bot_id, chat_id, repo_id, sub.id, kind
        )
        return sub

    async def remove(self, bot_id: int, chat_id: int, sub_id: int) -> bool:
        res = await self.session.execute(
            delete(GithubSubscription).where(
                GithubSubscription.id == sub_id,
                GithubSubscription.bot_id == bot_id,
                GithubSubscription.chat_id == chat_id,
            )
        )
        await self.session.commit()
        return bool(res.rowcount)

    async def remove_all(self, bot_id: int, chat_id: int) -> int:
        res = await self.session.execute(
            delete(GithubSubscription).where(
                GithubSubscription.bot_id == bot_id, GithubSubscription.chat_id == chat_id
            )
        )
        await self.session.commit()
        return res.rowcount or 0

    async def delete(self, sub_id: int) -> bool:
        row = await self.get(sub_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def page(
        self, offset: int = 0, limit: int = 50
    ) -> tuple[list[tuple[GithubSubscription, Repo]], int]:
        total = await self.session.scalar(select(func.count()).select_from(GithubSubscription)) or 0
        rows = await self.session.execute(
            select(GithubSubscription, Repo)
            .join(Repo, Repo.id == GithubSubscription.repo_id)
            .order_by(GithubSubscription.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(s, r) for s, r in rows], int(total)
