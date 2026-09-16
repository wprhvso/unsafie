from __future__ import annotations

import asyncio
from typing import Any

from .formatter import LLMResponse, format_chat_prompt
from .pool import AistudioPoolManager

_global_pool: AistudioPoolManager | None = None
_init_lock = asyncio.Lock()


async def get_default_pool() -> AistudioPoolManager:
    global _global_pool
    if _global_pool is None:
        async with _init_lock:
            if _global_pool is None:
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
        raw_output = await pool.generate_with_retry(prompt)
        return LLMResponse(raw_output)

    async def chat(self, messages: list[Any]) -> LLMResponse:
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
