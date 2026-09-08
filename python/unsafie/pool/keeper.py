import logging
from datetime import UTC, datetime

from unsafie import cluster
from unsafie.database.models.pool import PoolDonor
from unsafie.github.client.base import GithubHTTP
from unsafie.github.errors import GithubError
from unsafie.loop import Loop
from unsafie.pool import donors, keys, leases, registry
from unsafie.settings import settings

logger = logging.getLogger(__name__)

LIVE = ("in_progress", "queued", "waiting")


def _age(run: dict) -> float:
    created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
    return (datetime.now(UTC) - created).total_seconds()


async def runs(http: GithubHTTP, donor: PoolDonor) -> list[dict]:
    found: dict[int, dict] = {}
    for status in LIVE:
        answer = await http.request(
            "GET",
            f"/repos/{donor.repo}/actions/workflows/{donor.workflow}/runs",
            params={"status": status, "per_page": 100},
        )
        for run in answer.get("workflow_runs", []):
            found[int(run["id"])] = run
    return sorted(found.values(), key=lambda run: str(run["created_at"]), reverse=True)


async def reconcile(donor: PoolDonor) -> dict:
    http = GithubHTTP(donor.token)
    live = await runs(http, donor)
    old = [run for run in live if _age(run) > settings.pool_job_ttl]
    for run in old[: settings.pool_launch_burst]:
        await http.request("POST", f"/repos/{donor.repo}/actions/runs/{run['id']}/cancel")
        logger.info("pool donor %s: run %s retired at %.0fs", donor.login, run["id"], _age(run))
    kept = [run for run in live if run not in old]
    missing = max(0, donor.jobs - len(kept))
    launched = 0
    if missing:
        repo = await http.request("GET", f"/repos/{donor.repo}")
        branch = repo.get("default_branch") or "main"
        for _ in range(min(missing, settings.pool_launch_burst)):
            await http.request(
                "POST",
                f"/repos/{donor.repo}/actions/workflows/{donor.workflow}/dispatches",
                json_body={"ref": branch},
            )
            launched += 1
    await donors.note(donor.id, "ready")
    return {"live": len(kept), "retired": len(old), "launched": launched, "target": donor.jobs}


class Keeper(Loop):
    name = "pool.keeper"
    interval = 30.0
    min_interval = 10.0

    def __init__(self) -> None:
        super().__init__()
        self.enabled = settings.pool_enabled and settings.runs_worker
        self.interval = settings.pool_keeper_interval

    async def tick(self) -> None:
        await registry.reap()
        await leases.reap()
        for donor in await donors.all_donors(enabled_only=True):
            async with cluster.try_lock(keys.keeper(donor.id), ttl=120.0) as held:
                if not held:
                    continue
                try:
                    stats = await reconcile(donor)
                except GithubError as refused:
                    await donors.note(donor.id, "error", str(refused)[:500])
                    logger.warning("pool donor %s: %s", donor.login, refused)
                    continue
                logger.info(
                    "pool donor %s live=%s target=%s launched=%s retired=%s idle=%s",
                    donor.login,
                    stats["live"],
                    stats["target"],
                    stats["launched"],
                    stats["retired"],
                    await registry.idle_count(),
                )


keeper = Keeper()
