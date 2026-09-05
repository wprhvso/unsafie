import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

GetBot = Callable[[int], Any]


class Loop:
    name: str = "loop"
    interval: float = 60.0
    enabled: bool = True
    startup_delay: float = 3.0
    min_interval: float = 5.0

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.get_bot: GetBot | None = None

    async def tick(self) -> None:
        raise NotImplementedError

    def start(self, get_bot: GetBot | None = None) -> None:
        if not self.enabled:
            logger.info("%s disabled", self.name)
            return
        if self._task is not None:
            return
        self.get_bot = get_bot
        self._task = asyncio.create_task(self._run(), name=self.name)
        logger.info("%s started interval=%ss", self.name, self.interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        await self.on_stop()
        logger.info("%s stopped", self.name)

    async def on_stop(self) -> None:
        return None

    async def _run(self) -> None:
        await asyncio.sleep(self.startup_delay)
        while True:
            started = time.perf_counter()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s tick failed", self.name)
            logger.debug(
                "%s tick done in %.1fms", self.name, (time.perf_counter() - started) * 1000
            )
            await asyncio.sleep(max(self.min_interval, self.interval))


async def stop_all(loops: list[Loop]) -> None:
    for loop in reversed(loops):
        await loop.stop()
