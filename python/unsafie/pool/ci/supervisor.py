import asyncio
import contextlib
import logging

from unsafie.errors import OpsError
from unsafie.loop import Loop
from unsafie.pool.ci import repos
from unsafie.pool.ci.controller import Controller
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class CiSupervisor(Loop):
    name = "pool.ci"
    interval = 30.0
    min_interval = 10.0

    def __init__(self) -> None:
        super().__init__()
        self.enabled = settings.pool_enabled and settings.pool_ci_enabled and settings.runs_worker
        self.interval = settings.pool_ci_interval
        self.tasks: dict[int, asyncio.Task] = {}

    async def tick(self) -> None:
        await repos.close_orphans()
        wanted = {row.id: row for row in await repos.enabled_repos()}
        for repo_id, task in list(self.tasks.items()):
            if task.done():
                self.tasks.pop(repo_id, None)
                continue
            if repo_id not in wanted:
                await self._drop(repo_id, task)
        for repo_id, row in wanted.items():
            if repo_id in self.tasks:
                continue
            try:
                token = await repos.token_for(row.user_id)
            except OpsError as refused:
                await repos.note(repo_id, "error", str(refused)[:500])
                continue
            controller = Controller(row, token)
            self.tasks[repo_id] = asyncio.create_task(
                controller.serve(), name=f"pool.ci:{row.slug}",
            )
            logger.info("pool ci %s: controller scheduled", row.slug)

    async def _drop(self, repo_id: int, task: asyncio.Task) -> None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
            await asyncio.wait_for(task, timeout=2.0)
        self.tasks.pop(repo_id, None)

    async def on_stop(self) -> None:
        tasks = list(self.tasks.items())
        for _, task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(
                *(self._drop(repo_id, task) for repo_id, task in tasks),
                return_exceptions=True,
            )
        self.tasks.clear()


ci_supervisor = CiSupervisor()
