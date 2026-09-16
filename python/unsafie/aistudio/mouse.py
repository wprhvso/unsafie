from __future__ import annotations

import asyncio
import math
import random
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

import structlog
from pycdp.cdp import input_

if TYPE_CHECKING:
    from collections.abc import Generator

logger = structlog.get_logger()
T = TypeVar("T")


class CdpExecutor(Protocol):
    async def execute(
        self,
        cdp_generator: Generator[Any, Any, T],
        session_id: str | None = None,
    ) -> T: ...


class HumanMouse:
    def __init__(
        self, browser: CdpExecutor, current_x: float = 0.0, current_y: float = 0.0
    ) -> None:
        self.browser = browser
        self.current_x = current_x
        self.current_y = current_y

    async def move_to(
        self,
        target_x: float,
        target_y: float,
        steps: int | None = None,
    ) -> None:
        start_x, start_y = self.current_x, self.current_y
        distance = math.hypot(target_x - start_x, target_y - start_y)

        if steps is None:
            steps = max(18, int(distance / 12))

        ctrl1_x = (
            start_x + (target_x - start_x) * random.uniform(0.15, 0.4) + random.uniform(-30, 30)
        )
        ctrl1_y = (
            start_y + (target_y - start_y) * random.uniform(0.15, 0.4) + random.uniform(-30, 30)
        )
        ctrl2_x = (
            start_x + (target_x - start_x) * random.uniform(0.6, 0.85) + random.uniform(-20, 20)
        )
        ctrl2_y = (
            start_y + (target_y - start_y) * random.uniform(0.6, 0.85) + random.uniform(-20, 20)
        )

        for i in range(1, steps + 1):
            raw_t = i / steps
            t = 0.5 * (1 - math.cos(math.pi * raw_t))

            cur_x = (
                (1 - t) ** 3 * start_x
                + 3 * (1 - t) ** 2 * t * ctrl1_x
                + 3 * (1 - t) * t**2 * ctrl2_x
                + t**3 * target_x
            )
            cur_y = (
                (1 - t) ** 3 * start_y
                + 3 * (1 - t) ** 2 * t * ctrl1_y
                + 3 * (1 - t) * t**2 * ctrl2_y
                + t**3 * target_y
            )

            await self.browser.execute(
                input_.dispatch_mouse_event(
                    type_="mouseMoved",
                    x=cur_x,
                    y=cur_y,
                )
            )
            self.current_x = cur_x
            self.current_y = cur_y
            await asyncio.sleep(random.uniform(0.006, 0.018))

    async def click(self) -> None:
        await asyncio.sleep(random.uniform(0.06, 0.14))
        await self.browser.execute(
            input_.dispatch_mouse_event(
                type_="mousePressed",
                x=self.current_x,
                y=self.current_y,
                button=input_.MouseButton.LEFT,
                buttons=1,
                click_count=1,
            )
        )
        await asyncio.sleep(random.uniform(0.05, 0.12))
        await self.browser.execute(
            input_.dispatch_mouse_event(
                type_="mouseReleased",
                x=self.current_x,
                y=self.current_y,
                button=input_.MouseButton.LEFT,
                buttons=0,
                click_count=1,
            )
        )
        await asyncio.sleep(random.uniform(0.08, 0.2))

    async def click_at(self, target_x: float, target_y: float) -> None:
        await self.move_to(target_x, target_y)
        await self.click()
