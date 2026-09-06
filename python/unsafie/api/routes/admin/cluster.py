from fastapi import APIRouter
from sqlalchemy import text

from unsafie.database import SessionLocal

router = APIRouter(prefix="/cluster", tags=["cluster"])


@router.get("")
async def state() -> dict:
    async with SessionLocal() as session:
        cluster = (
            await session.execute(
                text("SELECT term, leader, reason, durable, updated_at FROM cluster_state WHERE id=1")
            )
        ).mappings().first()
        nodes = (
            await session.execute(
                text("SELECT id, priority, role, healthy, lsn, last_seen FROM nodes ORDER BY priority DESC")
            )
        ).mappings().all()
        jobs = (
            await session.execute(
                text("SELECT state, count(*) AS n FROM jobs GROUP BY state")
            )
        ).mappings().all()
    return {
        "cluster": dict(cluster) if cluster else {},
        "nodes": [dict(n) for n in nodes],
        "jobs": {row["state"]: row["n"] for row in jobs},
    }


@router.get("/metrics")
async def metrics(node: str | None = None, limit: int = 120) -> dict:
    clause = "WHERE node = :node" if node else ""
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    f"SELECT node, at, values FROM metric_samples {clause} "
                    "ORDER BY at DESC LIMIT :limit"
                ).bindparams(**({"node": node} if node else {}), limit=min(limit, 1000))
            )
        ).mappings().all()
    return {"samples": [dict(r) for r in rows]}
