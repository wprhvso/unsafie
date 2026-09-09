import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import aiohttp

from unsafie import telemetry
from unsafie.log import short
from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
RETRYABLE_KINDS = frozenset(
    {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL", "ABORTED"}
)

_session: aiohttp.ClientSession | None = None
_lock = asyncio.Lock()


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        kind: str,
        message: str,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{status} {kind}: {message}")
        self.status = status
        self.kind = kind
        self.message = message
        self.request_id = request_id
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE_STATUS or self.kind in RETRYABLE_KINDS

    def describe(self) -> str:
        tail = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.status} {self.kind}: {self.message}{tail}"


@dataclass
class Reply:
    id: str = ""
    model: str = ""
    text: str = ""
    thoughts: str = ""
    thought_signatures: list[str] = field(default_factory=list)
    raw_parts: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    raw: list[dict] = field(default_factory=list)

    @property
    def content(self) -> list[dict]:
        return self.raw_parts if self.raw_parts else ([{"type": "text", "text": self.text}] if self.text else [])

    @property
    def calls(self) -> list[dict]:
        return []

    def as_message(self) -> dict:
        # Сохраняем raw_parts (мысли + сигнатуры + код), обеспечивая сохранение цепочки рассуждений в многоходовом диалоге
        return {"role": "assistant", "content": self.raw_parts if self.raw_parts else self.text}

    def dump(self) -> dict:
        data = {
            "model": self.model,
            "text": self.text,
            "thoughts": self.thoughts,
            "thought_signatures": self.thought_signatures,
            "raw_parts": self.raw_parts,
            "stop_reason": self.stop_reason,
            "usage": self.usage,
            "raw": self.raw,
        }
        if self.id:
            data["id"] = self.id
        return data


async def session() -> aiohttp.ClientSession:
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _lock:
        if _session is None or _session.closed:
            connector = aiohttp.TCPConnector(
                limit=settings.gemini_connections,
                limit_per_host=settings.gemini_connections,
                ttl_dns_cache=300,
            )
            _session = aiohttp.ClientSession(connector=connector)
            logger.info("gemini http pool opened (limit=%s)", settings.gemini_connections)
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        logger.info("gemini http pool closed")
    _session = None


def headers(access_token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Origin": "https://opal.google",
        "User-Agent": "unsafie",
    }


class Builder:
    def __init__(self, model: str) -> None:
        self.reply = Reply(model=model)

    def feed(self, data: dict, on_event: Callable[[str, dict], None] | None) -> None:
        self.reply.raw.append(data)
        candidates = data.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                self.reply.raw_parts.append(dict(part))

                sig = part.get("thoughtSignature") or part.get("signature")
                if sig:
                    self.reply.thought_signatures.append(sig)
                    if on_event:
                        on_event("thought_signature", {"signature": sig})

                text = part.get("text")
                if not text:
                    continue

                if part.get("thought") is True:
                    self.reply.thoughts += text
                    if on_event:
                        on_event("thought_delta", {"thought": text})
                else:
                    self.reply.text += text
                    if on_event:
                        on_event("text_delta", {"text": text})

            finish_reason = candidate.get("finishReason")
            if finish_reason:
                self.reply.stop_reason = str(finish_reason)

        usage = data.get("usageMetadata")
        if isinstance(usage, dict):
            mapped = {
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            }
            self.reply.usage.update(mapped)
            if on_event:
                on_event("message_delta", {"usage": mapped, "stop_reason": self.reply.stop_reason})

    def result(self) -> Reply:
        return self.reply


async def _lines(stream: aiohttp.StreamReader) -> AsyncIterator[bytes]:
    buffer = b""
    async for chunk in stream.iter_any():
        buffer += chunk
        while True:
            cut = buffer.find(b"\n")
            if cut < 0:
                break
            line, buffer = buffer[:cut], buffer[cut + 1 :]
            yield line.rstrip(b"\r")
    if buffer:
        yield buffer.rstrip(b"\r")


async def _events(stream: aiohttp.StreamReader) -> AsyncIterator[dict]:
    async for raw in _lines(stream):
        line = raw.decode("utf-8", "replace").strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except ValueError:
            logger.warning("gemini sent unparsable sse data: %s", short(payload, 300))
            continue
        if isinstance(data, dict):
            yield data


def _failure(status: int, raw: bytes, request_id: str | None, retry_after: str | None) -> ApiError:
    kind = "HTTP_ERROR"
    message = short(raw.decode("utf-8", "replace"), 500)
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            kind = error.get("status") or str(error.get("code") or kind)
            message = error.get("message") or message
    wait = float(retry_after.strip()) if retry_after and retry_after.strip().isdigit() else None
    return ApiError(status, kind, message, request_id, wait)


async def _read(
    stream: aiohttp.StreamReader,
    model: str,
    on_event: Callable[[str, dict], None] | None,
) -> Reply:
    builder = Builder(model=model)
    if on_event:
        on_event("message_start", {"model": model})
    async for data in _events(stream):
        if "error" in data:
            error = data["error"] or {}
            raise ApiError(
                200,
                error.get("status") or "API_ERROR",
                error.get("message") or "stream returned error",
            )
        builder.feed(data, on_event)
    return builder.result()


async def _once(
    access_token: str,
    model: str,
    body: dict,
    attempt: int,
    on_event: Callable[[str, dict], None] | None,
) -> Reply:
    http = await session()
    url = f"{settings.gemini_api_url.rstrip('/')}/{model}:streamGenerateContent?alt=sse"
    sent = headers(access_token)
    timeout = aiohttp.ClientTimeout(
        total=settings.gemini_timeout,
        connect=settings.gemini_connect_timeout,
        sock_read=settings.gemini_read_timeout,
    )
    started = time.perf_counter()
    with telemetry.span(
        f"gemini POST {model}:streamGenerateContent",
        kind=telemetry.CLIENT,
        attributes={
            attrs.HTTP_METHOD: "POST",
            attrs.HTTP_URL: url,
            attrs.SERVER_ADDRESS: urlparse(url).hostname,
            attrs.GEN_AI_SYSTEM: "gemini",
            attrs.GEN_AI_MODEL: model,
            attrs.ATTEMPT: attempt if attempt > 1 else None,
        },
    ) as span:
        try:
            async with http.post(url, headers=sent, json=body, timeout=timeout) as response:
                request_id = response.headers.get("x-request-id")
                telemetry.set_attrs(
                    span, {attrs.HTTP_STATUS: response.status, attrs.REQUEST_ID: request_id}
                )
                if response.status >= 400:
                    raw = await response.read()
                    raise _failure(
                        response.status,
                        raw,
                        request_id,
                        response.headers.get("retry-after"),
                    )
                reply = await _read(response.content, model, on_event)
        except TimeoutError as e:
            raise ApiError(
                0, "DEADLINE_EXCEEDED", f"no answer in {settings.gemini_timeout:.0f}s"
            ) from e
        except aiohttp.ClientError as e:
            raise ApiError(0, "UNAVAILABLE", f"{type(e).__name__}: {e}") from e
        telemetry.set_attrs(
            span,
            {
                attrs.GEN_AI_INPUT_TOKENS: reply.usage.get("input_tokens"),
                attrs.GEN_AI_OUTPUT_TOKENS: reply.usage.get("output_tokens"),
                attrs.GEN_AI_FINISH_REASONS: [reply.stop_reason] if reply.stop_reason else None,
            },
        )
    logger.info(
        "gemini %s stop=%s in=%s out=%s (%.0fms)",
        model,
        reply.stop_reason,
        reply.usage.get("input_tokens"),
        reply.usage.get("output_tokens"),
        (time.perf_counter() - started) * 1000,
    )
    return reply


async def send(
    access_token: str,
    model: str,
    body: dict,
    *,
    on_event: Callable[[str, dict], None] | None = None,
) -> Reply:
    delay = settings.gemini_retry_base
    for attempt in range(1, settings.gemini_retries + 1):
        try:
            return await _once(access_token, model, body, attempt, on_event)
        except ApiError as e:
            if not e.retryable or attempt >= settings.gemini_retries:
                raise
            wait = min(e.retry_after or delay, settings.gemini_retry_max)
            telemetry.event(
                "gemini.retry",
                {"attempt": attempt, "status": e.status, "kind": e.kind, "sleep_sec": wait},
            )
            logger.warning("gemini %s, retrying in %.1fs", e.describe(), wait)
            await asyncio.sleep(wait)
            delay *= 2
    raise ApiError(0, "INTERNAL", "retries exhausted")
