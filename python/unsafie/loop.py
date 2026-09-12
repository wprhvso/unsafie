import asyncio
import contextlib
from unsafie.log import get_logger
import time

from unsafie import telemetry

logger = get_logger(__name__)


class Loop:
    name: str = "loop"
    interval: float = 60.0
    enabled: bool = True
    startup_delay: float = 3.0
    min_interval: float = 5.0

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def tick(self) -> None:
        raise NotImplementedError

    def start(self) -> None:
        if not self.enabled:
            logger.info("%s disabled", self.name)
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=self.name)
        logger.info("%s started interval=%ss", self.name, self.interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(self._task, timeout=5.0)
        self._task = None
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(self.on_stop(), timeout=5.0)
        logger.info("%s stopped", self.name)

    async def on_stop(self) -> None:
        return None

    async def _run(self) -> None:
        await asyncio.sleep(self.startup_delay)
        while True:
            started = time.perf_counter()
            try:
                with telemetry.detached():
                    await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s tick failed", self.name)
            logger.debug(
                "%s tick done in %.1fms", self.name, (time.perf_counter() - started) * 1000,
            )
            await asyncio.sleep(max(self.min_interval, self.interval))
