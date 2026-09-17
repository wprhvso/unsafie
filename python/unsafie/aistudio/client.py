from __future__ import annotations

import asyncio
import time
from typing import Any

from unsafie.log import get_logger

from .formatter import LLMResponse, format_chat_prompt
from .pool import AistudioPoolManager

logger = get_logger(__name__)

_global_pool: AistudioPoolManager | None = None
_init_lock = asyncio.Lock()


def get_pool_instance() -> AistudioPoolManager | None:
    return _global_pool


async def get_default_pool() -> AistudioPoolManager:
    global _global_pool
    if _global_pool is None:
        async with _init_lock:
            if _global_pool is None:
                logger.info("aistudio.pool.init")
                pool = AistudioPoolManager.from_env()
                await pool.start()
                _global_pool = pool
    return _global_pool


class AistudioClient:
    def __init__(self, pool: AistudioPoolManager | None = None) -> None:
        self._pool = pool

    async def _get_pool(self) -> AistudioPoolManager:
        if self._pool is None:
            self._pool = await get_default_pool()
        return self._pool

    async def generate(self, prompt: str) -> LLMResponse:
        pool = await self._get_pool()
        logger.info(
            "aistudio.generate.started",
            prompt_len=len(prompt),
            prompt_preview=prompt[:300],
        )
        started = time.perf_counter()
        raw_output = await pool.generate_with_retry(prompt)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "aistudio.generate.completed",
            duration_ms=elapsed_ms,
            output_len=len(raw_output),
            output_preview=str(raw_output)[:300],
        )
        return LLMResponse(raw_output)

    async def chat(self, messages: list[Any]) -> LLMResponse:
        logger.info("aistudio.chat.started", messages_count=len(messages))
        formatted_prompt = format_chat_prompt(messages)
        return await self.generate(formatted_prompt)

    async def complete(self, prompt_or_messages: Any) -> LLMResponse:
        if isinstance(prompt_or_messages, str):
            return await self.generate(prompt_or_messages)
        return await self.chat(prompt_or_messages)

    async def __call__(self, prompt_or_messages: Any) -> LLMResponse:
        return await self.complete(prompt_or_messages)


_default_client: AistudioClient | None = None


def get_default_client() -> AistudioClient:
    global _default_client
    if _default_client is None:
        _default_client = AistudioClient()
    return _default_client


async def generate(prompt: str) -> LLMResponse:
    client = get_default_client()
    return await client.generate(prompt)


async def chat(messages: list[Any]) -> LLMResponse:
    client = get_default_client()
    return await client.chat(messages)
