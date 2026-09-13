import shutil
from pathlib import Path

from unsafie.database import SessionLocal
from unsafie.database.repositories.ci import CiRepository
from unsafie.github.ci import checks
from unsafie.log import get_logger
from unsafie.loop import Loop
from unsafie.settings import settings

logger = get_logger(__name__)

WORKSPACES_DIR = Path("/var/lib/unsafie/ci/workspaces")

class CiJanitor(Loop):
    name = "ci-janitor"
    startup_delay = 10.0
    min_interval = 5.0

    @property
    def enabled(self) -> bool:
        return settings.runs_worker

    @property
    def interval(self) -> float:
        return 15.0

    async def tick(self) -> None:
        async with SessionLocal() as session:
            stale = await CiRepository(session).find_stale_runs()

        for run in stale:
            logger.warning("recovering stale crashed ci run %s (%s)", run.id, run.repo_full_name)
            async with SessionLocal() as session:
                await CiRepository(session).finish_run(
                    run.id,
                    status="crash",
                    exit_code=137,
                    error_message="Runner process terminated unexpectedly (SIGKILL or host reboot)",
                )

            if run.check_run_id:
                try:
                    await checks.update_check_run(
                        run.installation_id,
                        run.repo_full_name,
                        run.check_run_id,
                        status="completed",
                        conclusion="failure",
                        title="Runner Terminated",
                        summary="The CI execution process was killed abruptly (SIGKILL or OOM).",
                    )
                except Exception:
                    logger.exception("failed to notify github about crashed run %s", run.id)

            ws = WORKSPACES_DIR / str(run.id)
            if ws.exists():
                shutil.rmtree(ws, ignore_errors=True)

ci_janitor = CiJanitor()
