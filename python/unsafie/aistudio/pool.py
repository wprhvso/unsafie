from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import aiohttp
import structlog
from attrs import define, field

from unsafie.settings import settings

from .browser import AistudioBrowser, RateLimitError

logger = structlog.get_logger()


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
        return cls(endpoint=endpoint, max_active_profiles=max_profiles, cooldown_seconds=cooldown)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def load_profiles(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        url = f"{self.endpoint}/profiles"
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                else:
                    fallback_url = f"{self.endpoint}/profile"
                    async with session.get(fallback_url) as fallback_resp:
                        data = await fallback_resp.json()
        except Exception:
            data = []

        matching = [p for p in data if "aistudio-api" in p.get("tags", [])]
        if not matching:
            matching = data

        self._all_matching_profiles = matching
        return self._all_matching_profiles

    async def start(self) -> None:
        async with self._pool_lock:
            if self._is_started:
                return

            await self._ensure_session()
            profiles = await self.load_profiles()
            if not profiles:
                msg = "No browser profiles found in Kameleo"
                raise RuntimeError(msg)

            target_count = min(len(profiles), self.max_active_profiles)

            async def init_worker(p: dict[str, Any]) -> None:
                pid = p["id"]
                assert self._session is not None
                b = AistudioBrowser(session=self._session, profile=p, endpoint=self.endpoint)
                await b.__aenter__()
                await b.monopolize_tabs("https://aistudio.google.com")
                mp = ManagedProfile(profile_id=pid, profile_data=p, browser=b, is_running=True)
                self._managed[pid] = mp

            await asyncio.gather(*[init_worker(p) for p in profiles[:target_count]])
            self._is_started = True

    async def stop(self) -> None:
        async with self._pool_lock:
            if not self._is_started:
                return

            for mp in list(self._managed.values()):
                with contextlib.suppress(Exception):
                    await mp.browser.__aexit__(None, None, None)
            self._managed.clear()

            if self._session and not self._session.closed:
                await self._session.close()

            self._is_started = False

    async def acquire_profile(self) -> ManagedProfile:
        if not self._is_started:
            await self.start()

        loop = asyncio.get_running_loop()
        while True:
            now = loop.time()
            for mp in self._managed.values():
                if not mp.is_busy and mp.is_running and now >= mp.rate_limited_until:
                    mp.is_busy = True
                    return mp

            running_ids = set(self._managed.keys())
            unstarted = [p for p in self._all_matching_profiles if p["id"] not in running_ids]

            all_active_429 = all(now < mp.rate_limited_until for mp in self._managed.values())
            if all_active_429 and unstarted:
                spare = unstarted[0]
                assert self._session is not None
                b = AistudioBrowser(session=self._session, profile=spare, endpoint=self.endpoint)
                await b.__aenter__()
                await b.monopolize_tabs("https://aistudio.google.com")
                mp = ManagedProfile(
                    profile_id=spare["id"],
                    profile_data=spare,
                    browser=b,
                    is_running=True,
                    is_busy=True,
                )
                self._managed[spare["id"]] = mp
                return mp

            await asyncio.sleep(0.3)

    def release_profile(self, profile: ManagedProfile, rate_limited: bool = False) -> None:
        profile.is_busy = False
        if rate_limited:
            now = asyncio.get_running_loop().time()
            profile.rate_limited_until = now + self.cooldown_seconds

    async def generate_with_retry(self, prompt: str, max_retries: int | None = None) -> str:
        retries = 0
        limit = max_retries if max_retries is not None else max(3, len(self._managed))
        last_error: Exception | None = None

        while retries < limit:
            mp = await self.acquire_profile()
            async with mp.lock:
                try:
                    result = await mp.browser.generate_content(prompt)
                    self.release_profile(mp, rate_limited=False)
                    return result
                except RateLimitError as e:
                    self.release_profile(mp, rate_limited=True)
                    last_error = e
                    retries += 1
                    continue
                except Exception as e:
                    self.release_profile(mp, rate_limited=False)
                    last_error = e
                    retries += 1
                    await asyncio.sleep(1.0)
                    continue

        msg = f"All AI Studio profiles failed or are rate-limited: {last_error}"
        raise RuntimeError(msg)
