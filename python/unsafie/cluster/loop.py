import logging

from sqlalchemy import text

from unsafie.cluster import gossip
from unsafie.cluster.election import election
from unsafie.database import SessionLocal
from unsafie.loop import Loop
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class ElectionLoop(Loop):
    name = "cluster-election"
    startup_delay = 2.0

    @property
    def enabled(self) -> bool:
        return len(settings.peers) > 0

    @property
    def interval(self) -> float:
        return settings.gossip_interval

    async def on_start(self) -> None:
        election.gossip = await gossip.bind()

    async def tick(self) -> None:
        await self._read_lsn()
        await election.tick()

    async def _read_lsn(self) -> None:
        try:
            async with SessionLocal() as session:
                row = await session.execute(
                    text(
                        "SELECT CASE WHEN pg_is_in_recovery() "
                        "THEN pg_last_wal_replay_lsn()::text "
                        "ELSE pg_current_wal_lsn()::text END"
                    )
                )
                election.local_lsn = row.scalar() or "0/0"
        except Exception as e:
            logger.debug("lsn read failed: %s", e)


election_loop = ElectionLoop()
