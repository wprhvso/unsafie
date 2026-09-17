from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import aiohttp
from attrs import define, field

from unsafie.log import get_logger
from unsafie.settings import settings

from .browser import AistudioBrowser, RateLimitError, UnusableProfileError

logger = get_logger(__name__)


@define
class ManagedProfile:
    profile_id: str
    profile_data: dict[str, Any]
    browser: AistudioBrowser
    lock: asyncio.Lock = field(factory=asyncio.Lock)
    rate_limited_until: float = 0.0
    is_busy: bool = False
    is_running: bool = False


@define
class AistudioPoolManager:
    endpoint: str = field(default="http://localhost:5050")
    max_active_profiles: int = field(default=3)
    cooldown_seconds: float = field(default=60.0)
    _session: aiohttp.ClientSession | None = None
    _all_matching_profiles: list[dict[str, Any]] = field(factory=list)
    _managed: dict[str, ManagedProfile] = field(factory=dict)
    _pool_lock: asyncio.Lock = field(factory=asyncio.Lock)
    _is_started: bool = False

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
        max_profiles = int(os.getenv("AISTUDIO_MAX_PROFILES", "3"))
        cooldown = float(os.getenv("AISTUDIO_COOLDOWN", "60.0"))
        logger.info(
            "aistudio.pool.config",
            endpoint=endpoint,
            max_profiles=max_profiles,
            cooldown_seconds=cooldown,
        )
        return cls(endpoint=endpoint, max_active_profiles=max_profiles, cooldown_seconds=cooldown)

    def is_ready(self) -> bool:
        return self._is_started and any(mp.is_running for mp in self._managed.values())

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
        self._all_matching_profiles = matching
        return self._all_matching_profiles

    async def start(self) -> None:
        async with self._pool_lock:
            if self._is_started:
                return

            logger.info("aistudio.pool.starting")
            await self._ensure_session()
            profiles = await self.load_profiles()
            if not profiles:
                msg = "No browser profiles found in Kameleo"
                logger.error("aistudio.pool.start.error", reason=msg)
                raise RuntimeError(msg)

            logger.info(
                "aistudio.pool.workers.spawning",
                total_profiles=len(profiles),
                max_profiles=self.max_active_profiles,
            )

            async def init_worker(p: dict[str, Any]) -> ManagedProfile | None:
                pid = p["id"]
                name = p.get("name")
                logger.info("aistudio.pool.worker.init", profile_id=pid, name=name)
                assert self._session is not None
                b = AistudioBrowser(session=self._session, profile=p, endpoint=self.endpoint)
                try:
                    await b.__aenter__()
                    await b.monopolize_tabs("https://aistudio.google.com")
                    await b.check_welcome_page()
                    logger.info("aistudio.pool.worker.ready", profile_id=pid, name=name)
                    return ManagedProfile(profile_id=pid, profile_data=p, browser=b, is_running=True)
                except Exception as e:
                    logger.warning(
                        "aistudio.pool.worker.failed_to_start",
                        profile_id=pid,
                        name=name,
                        error=str(e),
                    )
                    with contextlib.suppress(Exception):
                        await b.close(stop_profile=False)
                    return None

            async def staggered_init(p: dict[str, Any], delay: float) -> ManagedProfile | None:
                if delay > 0:
                    await asyncio.sleep(delay)
                return await init_worker(p)

            results = await asyncio.gather(
                *[staggered_init(p, i * 0.8) for i, p in enumerate(profiles)]
            )
            healthy = [mp for mp in results if mp is not None]

            for mp in healthy:
                if len(self._managed) < self.max_active_profiles:
                    self._managed[mp.profile_id] = mp
                else:
                    with contextlib.suppress(Exception):
                        await mp.browser.close(stop_profile=False)

            if not self._managed:
                msg = "No healthy browser profiles could be started in Kameleo"
                logger.error("aistudio.pool.start.error", reason=msg)
                raise RuntimeError(msg)

            self._is_started = True
            logger.info(
                "aistudio.pool.started",
                active_workers=list(self._managed.keys()),
                healthy_count=len(self._managed),
                total_candidates=len(profiles),
            )

    async def stop(self, stop_kameleo: bool = False) -> None:
        async with self._pool_lock:
            if not self._is_started:
                return

            logger.info("aistudio.pool.stopping", workers=list(self._managed.keys()), stop_kameleo=stop_kameleo)
            for mp in list(self._managed.values()):
                with contextlib.suppress(Exception):
                    await mp.browser.close(stop_profile=stop_kameleo)
            self._managed.clear()

            if self._session and not self._session.closed:
                await self._session.close()

            self._is_started = False
            logger.info("aistudio.pool.stopped")

    async def acquire_profile(self) -> ManagedProfile:
        if not self._is_started:
            await self.start()

        loop = asyncio.get_running_loop()
        start_wait = loop.time()
        logger.info("aistudio.pool.acquire.request")
        while True:
            now = loop.time()
            for mp in list(self._managed.values()):
                if not mp.is_busy and mp.is_running and now >= mp.rate_limited_until:
                    mp.is_busy = True
                    logger.info(
                        "aistudio.pool.acquire.granted",
                        profile_id=mp.profile_id,
                        waited_ms=round((now - start_wait) * 1000, 2),
                    )
                    return mp

            running_ids = set(self._managed.keys())
            unstarted = [p for p in self._all_matching_profiles if p["id"] not in running_ids]

            all_active_429 = all(now < mp.rate_limited_until for mp in self._managed.values())
            if all_active_429 and unstarted:
                while unstarted:
                    spare = unstarted.pop(0)
                    pid = spare["id"]
                    logger.info("aistudio.pool.spawning_spare_worker", profile_id=pid)
                    assert self._session is not None
                    b = AistudioBrowser(session=self._session, profile=spare, endpoint=self.endpoint)
                    try:
                        await b.__aenter__()
                        await b.monopolize_tabs("https://aistudio.google.com")
                        await b.check_welcome_page()
                        mp = ManagedProfile(
                            profile_id=pid,
                            profile_data=spare,
                            browser=b,
                            is_running=True,
                            is_busy=True,
                        )
                        self._managed[pid] = mp
                        logger.info("aistudio.pool.spare_worker_ready", profile_id=pid)
                        return mp
                    except Exception as e:
                        logger.warning(
                            "aistudio.pool.spare_worker_failed",
                            profile_id=pid,
                            error=str(e),
                        )
                        with contextlib.suppress(Exception):
                            await b.close(stop_profile=False)
                        self._all_matching_profiles = [
                            p for p in self._all_matching_profiles if p.get("id") != pid
                        ]

            await asyncio.sleep(0.3)

    def release_profile(self, profile: ManagedProfile, rate_limited: bool = False) -> None:
        profile.is_busy = False
        if rate_limited:
            now = asyncio.get_running_loop().time()
            profile.rate_limited_until = now + self.cooldown_seconds
            logger.warning(
                "aistudio.pool.profile.rate_limited",
                profile_id=profile.profile_id,
                cooldown_until=round(profile.rate_limited_until, 2),
                duration=self.cooldown_seconds,
            )
        else:
            logger.info("aistudio.pool.profile.released", profile_id=profile.profile_id)

    async def generate_with_retry(self, prompt: str, max_retries: int | None = None) -> str:
        retries = 0
        limit = max_retries if max_retries is not None else max(3, len(self._managed))
        last_error: Exception | None = None

        logger.info(
            "aistudio.pool.generate_with_retry.started",
            max_retries=limit,
            managed_count=len(self._managed),
        )

        while retries < limit:
            mp = await self.acquire_profile()
            async with mp.lock:
                try:
                    logger.info(
                        "aistudio.pool.attempt.start",
                        attempt=retries + 1,
                        profile_id=mp.profile_id,
                    )
                    result = await mp.browser.generate_content(prompt)
                    self.release_profile(mp, rate_limited=False)
                    logger.info(
                        "aistudio.pool.attempt.success",
                        attempt=retries + 1,
                        profile_id=mp.profile_id,
                        result_len=len(result),
                    )
                    return result
                except UnusableProfileError as e:
                    logger.warning(
                        "aistudio.pool.profile.evicted_unusable",
                        profile_id=mp.profile_id,
                        error=str(e),
                    )
                    mp.is_running = False
                    self._managed.pop(mp.profile_id, None)
                    self._all_matching_profiles = [
                        p for p in self._all_matching_profiles if p.get("id") != mp.profile_id
                    ]
                    with contextlib.suppress(Exception):
                        await mp.browser.close(stop_profile=False)
                    last_error = e
                    retries += 1
                    continue
                except RateLimitError as e:
                    logger.warning(
                        "aistudio.pool.attempt.rate_limited",
                        attempt=retries + 1,
                        profile_id=mp.profile_id,
                        error=str(e),
                    )
                    self.release_profile(mp, rate_limited=True)
                    last_error = e
                    retries += 1
                    continue
                except Exception as e:
                    logger.exception(
                        "aistudio.pool.attempt.failed",
                        attempt=retries + 1,
                        profile_id=mp.profile_id,
                        error=str(e),
                    )
                    if "WebSocket is not connected" in str(e) or not mp.browser.is_connected:
                        mp.is_running = False
                        logger.warning("aistudio.pool.marking_worker_dead", profile_id=mp.profile_id)
                        with contextlib.suppress(Exception):
                            await mp.browser.reconnect()
                            mp.is_running = True
                    self.release_profile(mp, rate_limited=False)
                    last_error = e
                    retries += 1
                    await asyncio.sleep(0.5)
                    continue

        msg = f"All AI Studio profiles failed or are rate-limited: {last_error}"
        logger.error("aistudio.pool.exhausted", error=msg)
        raise RuntimeError(msg)
