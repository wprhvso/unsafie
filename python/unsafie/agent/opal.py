from __future__ import annotations

from typing import Any

from unsafie.aistudio.client import AistudioClient, chat, generate, get_default_client
from unsafie.aistudio.formatter import LLMResponse, format_chat_prompt


class OpalError(Exception):
    pass


class OpalRefreshFailed(OpalError):
    pass


async def refresh_access_token(refresh_token: str) -> str:
    return "aistudio-browser-token"


async def get_access_token(session_id: int, refresh_token: str) -> str:
    return "aistudio-browser-token"


async def get_random_access_token(exclude: set[int] | None = None) -> tuple[int, str] | None:
    return (1, "aistudio-browser-token")


async def invalidate(session_id: int) -> None:
    pass


class OpalProxy:
    def __init__(self) -> None:
        self.generate = generate
        self.chat = chat
        self.complete = generate
        self.invoke = generate
        self.format_chat_prompt = format_chat_prompt
        self.LLMResponse = LLMResponse
        self.OpalClient = AistudioClient
        self.Opal = AistudioClient
        self.Client = AistudioClient

    async def __call__(self, *args: Any, **kwargs: Any) -> LLMResponse:
        client = get_default_client()
        if args and isinstance(args[0], (list, tuple)):
            return await client.chat(args[0])
        if args and isinstance(args[0], str):
            return await client.generate(args[0])
        if "messages" in kwargs:
            return await client.chat(kwargs["messages"])
        if "prompt" in kwargs:
            return await client.generate(kwargs["prompt"])
        msg = "Either prompt or messages must be provided"
        raise ValueError(msg)


proxy_instance = OpalProxy()

generate = proxy_instance.generate
chat = proxy_instance.chat
complete = proxy_instance.complete
invoke = proxy_instance.invoke
format_chat_prompt = proxy_instance.format_chat_prompt
LLMResponse = proxy_instance.LLMResponse
OpalClient = proxy_instance.OpalClient
Opal = proxy_instance.Opal
Client = proxy_instance.Client
