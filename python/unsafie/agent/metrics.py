import logging

from sqlalchemy import text

from unsafie.database import SessionLocal
from unsafie.database.models.metric import MetricSample
from unsafie.loop import Loop
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class MetricsRollup(Loop):
    name = "metrics-rollup"
    interval = 60.0
    startup_delay = 30.0

    async def tick(self) -> None:
        async with SessionLocal() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM jobs WHERE state='ready') AS jobs_ready,
                      (SELECT count(*) FROM jobs WHERE state='running') AS jobs_running,
                      (SELECT count(*) FROM turns WHERE created_at > now() - interval '1 minute')
                        AS turns_last_min,
                      (SELECT count(*) FROM turns
                        WHERE status='failed' AND created_at > now() - interval '1 hour')
                        AS failed_last_hour,
                      (SELECT coalesce(sum(amount), 0) FROM holds WHERE expires_at > now())
                        AS held_units
                    """
                )
            )
            row = rows.mappings().one()
            session.add(MetricSample(node=settings.node_id, values=dict(row)))
            await session.commit()


rollup = MetricsRollup()
