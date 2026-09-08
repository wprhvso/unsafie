import asyncio
import json
import logging
import shlex
from datetime import UTC, datetime

from sqlalchemy import update

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.models.pool import MachineState, PoolCiRepo, PoolMachine
from unsafie.errors import OpsError
from unsafie.pool import channel, keys, registry
from unsafie.pool.ci import repos
from unsafie.pool.ci.scaleset import ScaleSet, ScaleSetError, Session
from unsafie.settings import settings
from unsafie_wire import channel as wire

logger = logging.getLogger(__name__)

JOB_MESSAGES = "RunnerScaleSetJobMessages"
BACKOFF_MIN = 5.0
BACKOFF_MAX = 120.0
RESET_STATUSES = (401, 404, 409)
STATS_EVERY = 5


class Controller:
    def __init__(self, repo: PoolCiRepo, token: str) -> None:
        self.repo = repo
        self.api = ScaleSet(repo.slug, token)
        self.scale_set_id = repo.scale_set_id or 0
        self.session: Session | None = None
        self.last_message = 0
        self.quiet = 0
        self.watchers: set[asyncio.Task] = set()

    @property
    def owner(self) -> str:
        return f"unsafie-{settings.instance_id}"

    async def serve(self) -> None:
        async with cluster.try_lock(keys.ci(self.repo.id), ttl=180.0, renew=True) as held:
            if held is None:
                return
            logger.info("pool ci %s: controller up", self.repo.slug)
            backoff = BACKOFF_MIN
            try:
                while True:
                    try:
                        await self._prepare()
                        await self._cycle()
                        backoff = BACKOFF_MIN
                    except asyncio.CancelledError:
                        raise
                    except ScaleSetError as refused:
                        await self._stumble(refused, refused.status)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, BACKOFF_MAX)
                    except OpsError as refused:
                        await self._stumble(refused, 0)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, BACKOFF_MAX)
            finally:
                await self._farewell()

    async def _stumble(self, problem: Exception, status: int) -> None:
        logger.warning("pool ci %s: %s", self.repo.slug, problem)
        await repos.note(self.repo.id, "error", str(problem)[:500])
        if status in RESET_STATUSES:
            self.session = None
            self.last_message = 0

    async def _prepare(self) -> None:
        if not self.scale_set_id:
            found = await self.api.ensure(self.repo.label)
            self.scale_set_id = int(found["id"])
            await repos.note(self.repo.id, "ready", None, self.scale_set_id)
        if self.session is None:
            self.session = await self.api.open(self.scale_set_id, self.owner)
            await repos.note(self.repo.id, "ready")
            await self._scale(self._assigned(self.session.statistics))
        elif self.session.stale:
            self.session = await self.api.refresh(self.scale_set_id, self.session)

    async def _cycle(self) -> None:
        if self.session is None:
            return
        room = await self._room()
        message = await self.api.poll(self.session, self.last_message, room)
        if message is None:
            self.quiet += 1
            if self.quiet >= STATS_EVERY:
                self.quiet = 0
                await self._scale(self._assigned(await self.api.statistics(self.scale_set_id)))
            return
        self.quiet = 0
        self.last_message = int(message.get("messageId") or self.last_message)
        await self.api.ack(self.session, self.last_message)
        if str(message.get("messageType") or "") != JOB_MESSAGES:
            return
        body = self._body(message)
        await self._acquire(body)
        await self._scale(self._assigned(body.get("statistics") or message.get("statistics")))

    @staticmethod
    def _body(message: dict) -> dict:
        raw = message.get("body")
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _assigned(statistics: object) -> int:
        if not isinstance(statistics, dict):
            return 0
        return int(statistics.get("totalAssignedJobs") or 0)

    async def _acquire(self, body: dict) -> None:
        if self.session is None:
            return
        wanted: list[int] = []
        for item in body.get("messages") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("messageType") or "") != "JobAvailable":
                continue
            request_id = item.get("runnerRequestId")
            if request_id is not None:
                wanted.append(int(request_id))
        if not wanted:
            return
        taken = await self.api.acquire(self.scale_set_id, self.session, wanted)
        logger.info("pool ci %s: acquired %s of %s job(s)", self.repo.slug, taken, len(wanted))

    async def _room(self) -> int:
        live = len(await repos.running_jobs(self.repo.id))
        idle = await registry.idle_count()
        free = max(0, idle - settings.pool_ci_reserve)
        return max(0, min(self.repo.jobs - live, free))

    async def _scale(self, assigned: int) -> None:
        live = len(await repos.running_jobs(self.repo.id))
        missing = min(max(0, assigned - live), self.repo.jobs - live)
        if missing <= 0:
            return
        for _ in range(missing):
            if not await self._launch():
                logger.info("pool ci %s: no free machine for a runner yet", self.repo.slug)
                return

    async def _launch(self) -> bool:
        machine = await registry.grab_idle()
        if machine is None:
            return False
        try:
            runner_id, runner_name, config = await self.api.jit(self.scale_set_id)
        except ScaleSetError:
            await registry.mark(machine, MachineState.IDLE)
            raise
        await self._occupy(machine)
        command = " ".join(
            [
                "unsafie ci-runner",
                "--jit",
                shlex.quote(config),
                "--name",
                shlex.quote(runner_name),
                "--repo",
                shlex.quote(self.repo.slug),
                "--idle",
                str(self.repo.idle),
                "--lifetime",
                str(self.repo.lifetime),
            ]
        )
        command_id = await channel.send(
            machine,
            command,
            user_id=self.repo.user_id,
            timeout=float(self.repo.lifetime + self.repo.idle + 600),
            background=True,
        )
        job = await repos.start_job(self.repo.id, machine, runner_name)
        watcher = asyncio.create_task(
            self._watch(machine, command_id, job.id, runner_id),
            name=f"pool.ci.runner:{machine}",
        )
        self.watchers.add(watcher)
        watcher.add_done_callback(self.watchers.discard)
        logger.info(
            "pool ci %s: runner %s dispatched to %s", self.repo.slug, runner_name, machine
        )
        return True

    async def _occupy(self, machine: str) -> None:
        await registry.mark(machine, MachineState.CI)
        async with SessionLocal() as session:
            await session.execute(
                update(PoolMachine)
                .where(PoolMachine.name == machine)
                .values(
                    state=MachineState.CI,
                    user_id=self.repo.user_id,
                    leased_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def _watch(self, machine: str, command_id: str, job_id: int, runner_id: int) -> None:
        patience = float(self.repo.lifetime + self.repo.idle + 900)
        try:
            result = await channel.collect(command_id, machine, patience)
            status = "done" if result.exit_code == 0 else "failed"
            tail = (result.output or "").strip().splitlines()
            await repos.finish_job(job_id, status, tail[-1][:200] if tail else None)
        except asyncio.CancelledError:
            await repos.finish_job(job_id, "cancelled", None)
            raise
        except Exception as broken:
            logger.warning("pool ci %s: runner on %s ended badly: %s", self.repo.slug, machine, broken)
            await repos.finish_job(job_id, "failed", str(broken)[:200])
        finally:
            await self.api.forget(runner_id)
            await channel.tell(machine, wire.shutdown("ci runner finished"))
            await registry.forget(machine, "ci runner finished")

    async def _farewell(self) -> None:
        for watcher in list(self.watchers):
            watcher.cancel()
        if self.session is not None:
            try:
                await self.api.close(self.scale_set_id, self.session)
            except (ScaleSetError, OSError) as refused:
                logger.debug("pool ci %s: session stayed open: %s", self.repo.slug, refused)
        logger.info("pool ci %s: controller down", self.repo.slug)
