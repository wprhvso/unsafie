from __future__ import annotations

import asyncio
import os
from typing import Any

import aiohttp
from attrs import define, field

from unsafie.log import get_logger
from unsafie.settings import settings

from .browser import AistudioBrowser, RateLimitError, UnusableProfileError

logger = get_logger(__name__)


@define
class AistudioPoolManager:
    endpoint: str = field(default="http://localhost:5050")
    max_concurrent: int = field(default=3)
    cooldown_seconds: float = field(default=60.0)
    _session: aiohttp.ClientSession | None = None
    _matching_profiles: list[dict[str, Any]] = field(factory=list)
    _busy_profiles: set[str] = field(factory=set)
    _rate_limited: dict[str, float] = field(factory=dict)
    _semaphore: asyncio.Semaphore = field(init=False)
    _lock: asyncio.Lock = field(factory=asyncio.Lock)

    def __attrs_post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    @classmethod
    def from_env(cls) -> AistudioPoolManager:
        endpoint = os.getenv(
            "KAMELEO_URL",
            os.getenv(
                "KAMELEO_ENDPOINT",
                os.getenv(
                    "AISTUDIO_ENDPOINT", getattr(settings, "kameleo_url", "http://localhost:5050")
                ),
            ),
        )
        max_concurrent = int(os.getenv("AISTUDIO_MAX_PROFILES", "3"))
        cooldown = float(os.getenv("AISTUDIO_COOLDOWN", "60.0"))
        logger.info(
            "aistudio.pool.config",
            endpoint=endpoint,
            max_concurrent=max_concurrent,
            cooldown_seconds=cooldown,
        )
        return cls(endpoint=endpoint, max_concurrent=max_concurrent, cooldown_seconds=cooldown)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def load_profiles(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        url = f"{self.endpoint}/profiles"
        logger.info("aistudio.pool.load_profiles.request", url=url)
        data = []
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                else:
                    fallback_url = f"{self.endpoint}/profile"
                    async with session.get(fallback_url) as fallback_resp:
                        data = await fallback_resp.json()
        except Exception as e:
            logger.exception("aistudio.pool.load_profiles.failed", error=str(e))
            data = []

        matching = [p for p in data if "aistudio-api" in p.get("tags", [])]
        if not matching:
            matching = data

        logger.info(
            "aistudio.pool.load_profiles.success",
            total_found=len(data),
            matching_found=len(matching),
            matching_ids=[p.get("id") for p in matching],
        )
        self._matching_profiles = matching
        return self._matching_profiles

    async def start(self) -> None:
        logger.info("aistudio.pool.starting")
        await self._ensure_session()
        profiles = await self.load_profiles()
        if not profiles:
            msg = "No browser profiles found in Kameleo"
            logger.error("aistudio.pool.start.error", reason=msg)
            raise RuntimeError(msg)
        logger.info("aistudio.pool.started", total_candidates=len(profiles))

    async def stop(self) -> None:
        logger.info("aistudio.pool.stopping")
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("aistudio.pool.stopped")

    async def _pick_available_profile(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        start_wait = loop.time()
        logger.info("aistudio.pool.acquire.request")
        while True:
            async with self._lock:
                now = loop.time()
                for p in self._matching_profiles:
                    pid = p["id"]
                    if pid not in self._busy_profiles and now >= self._rate_limited.get(pid, 0.0):
                        self._busy_profiles.add(pid)
                        logger.info(
                            "aistudio.pool.acquire.granted",
                            profile_id=pid,
                            waited_ms=round((now - start_wait) * 1000, 2),
                        )
                        return p
            await asyncio.sleep(0.5)

    async def generate_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        session = await self._ensure_session()
        if not self._matching_profiles:
            await self.load_profiles()

        last_error: Exception | None = None
        logger.info(
            "aistudio.pool.generate_with_retry.started",
            max_retries=max_retries,
            profiles_count=len(self._matching_profiles),
        )

        for attempt in range(max_retries):
            async with self._semaphore:
                p = await self._pick_available_profile()
                pid = p["id"]
                browser = AistudioBrowser(session=session, profile=p, endpoint=self.endpoint)

                try:
                    logger.info("aistudio.pool.attempt.start", attempt=attempt + 1, profile_id=pid)
                    async with browser:
                        result = await browser.generate_content(prompt)
                        logger.info(
                            "aistudio.pool.attempt.success",
                            attempt=attempt + 1,
                            profile_id=pid,
                            result_len=len(result),
                        )
                        return result
                except RateLimitError as e:
                    last_error = e
                    now = asyncio.get_running_loop().time()
                    self._rate_limited[pid] = now + self.cooldown_seconds
                    logger.warning(
                        "aistudio.pool.attempt.rate_limited",
                        attempt=attempt + 1,
                        profile_id=pid,
                        error=str(e),
                        cooldown=self.cooldown_seconds,
                    )
                except UnusableProfileError as e:
                    last_error = e
                    self._matching_profiles = [
                        mp for mp in self._matching_profiles if mp["id"] != pid
                    ]
                    logger.warning(
                        "aistudio.pool.attempt.unusable",
                        attempt=attempt + 1,
                        profile_id=pid,
                        error=str(e),
                    )
                except Exception as e:
                    last_error = e
                    logger.exception(
                        "aistudio.pool.attempt.failed",
                        attempt=attempt + 1,
                        profile_id=pid,
                        error=str(e),
                    )
                finally:
                    async with self._lock:
                        self._busy_profiles.discard(pid)
                    logger.info("aistudio.pool.profile.released", profile_id=pid)

        msg = f"All profile attempts failed: {last_error}"
        logger.error("aistudio.pool.exhausted", error=msg)
        raise RuntimeError(msg)
