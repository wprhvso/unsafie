import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.ssh_host import SshHost

logger = logging.getLogger(__name__)


class SshRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def hosts(self, user_id: int) -> list[SshHost]:
        return list(
            await self.session.scalars(
                select(SshHost).where(SshHost.user_id == user_id).order_by(SshHost.alias)
            )
        )

    async def get(self, host_id: int) -> SshHost | None:
        return await self.session.get(SshHost, host_id)

    async def host(self, user_id: int, ref: str) -> SshHost | None:
        ref = ref.strip()
        row = await self.session.scalar(
            select(SshHost).where(SshHost.user_id == user_id, SshHost.alias == ref)
        )
        if row is not None:
            return row
        username = None
        if "@" in ref:
            username, _, ref = ref.rpartition("@")
        port = None
        if ref.count(":") == 1:
            ref, _, p = ref.partition(":")
            if p.isdigit():
                port = int(p)
        cond = [SshHost.user_id == user_id, SshHost.host == ref]
        if username:
            cond.append(SshHost.username == username)
        if port:
            cond.append(SshHost.port == port)
        rows = list(await self.session.scalars(select(SshHost).where(*cond)))
        return rows[0] if len(rows) == 1 else None

    async def add(
        self,
        user_id: int,
        alias: str,
        host: str,
        port: int,
        username: str,
        host_key: str | None,
        fingerprint: str | None,
    ) -> SshHost:
        row = SshHost(
            user_id=user_id,
            alias=alias,
            host=host,
            port=port,
            username=username,
            host_key=host_key,
            fingerprint=fingerprint,
        )
        self.session.add(row)
        await self.session.commit()
        logger.info("user=%s ssh host=%s alias=%s added", user_id, row.label, alias)
        return row

    async def remove(self, user_id: int, ref: str) -> SshHost | None:
        row = await self.host(user_id, ref)
        if row is None:
            return None
        await self.session.delete(row)
        await self.session.commit()
        return row

    async def set_host_key(self, host_id: int, host_key: str, fingerprint: str) -> None:
        row = await self.get(host_id)
        if row is None:
            return
        row.host_key = host_key
        row.fingerprint = fingerprint
        await self.session.commit()

    async def touch(self, host_id: int) -> None:
        row = await self.get(host_id)
        if row is None:
            return
        row.last_used_at = datetime.now(UTC)
        await self.session.commit()

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[SshHost], int]:
        total = await self.session.scalar(select(func.count()).select_from(SshHost)) or 0
        rows = await self.session.scalars(
            select(SshHost).order_by(SshHost.id).offset(offset).limit(limit)
        )
        return list(rows), int(total)
