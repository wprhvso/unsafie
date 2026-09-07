import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import aiohttp

from unsafie import telemetry
from unsafie.database.models.credential import AnthropicCredential, CredentialKind
from unsafie.log import short
from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

PATH = "/v1/messages"
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
RETRYABLE_KINDS = frozenset({"overloaded_error", "api_error", "timeout_error", "network_error"})
JSON_BLOCKS = frozenset({"tool_use", "server_tool_use", "mcp_tool_use"})

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
    id: str | None = None
    model: str = ""
    content: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def calls(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    def as_message(self) -> dict:
        return {"role": "assistant", "content": self.content}


async def session() -> aiohttp.ClientSession:
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _lock:
        if _session is None or _session.closed:
            connector = aiohttp.TCPConnector(
                limit=settings.anthropic_connections,
                limit_per_host=settings.anthropic_connections,
                ttl_dns_cache=300,
            )
            _session = aiohttp.ClientSession(connector=connector)
            logger.info("anthropic http pool opened (limit=%s)", settings.anthropic_connections)
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        logger.info("anthropic http pool closed")
    _session = None


def betas(credential: AnthropicCredential) -> list[str]:
    marks = [b.strip() for b in settings.anthropic_beta.split(",") if b.strip()]
    if credential.kind == CredentialKind.OAUTH and settings.anthropic_oauth_beta:
        marks.append(settings.anthropic_oauth_beta)
    return list(dict.fromkeys(marks))


def headers(credential: AnthropicCredential) -> dict[str, str]:
    out = {
        "content-type": "application/json",
        "accept": "text/event-stream",
        "anthropic-version": settings.anthropic_version,
        "user-agent": f"unsafie/{settings.service_version or 'dev'}",
    }
    if credential.kind == CredentialKind.OAUTH:
        out["authorization"] = f"Bearer {credential.secret}"
    else:
        out["x-api-key"] = credential.secret
    marks = betas(credential)
    if marks:
        out["anthropic-beta"] = ",".join(marks)
    return out


class Builder:
    def __init__(self) -> None:
        self.reply = Reply()
        self._blocks: dict[int, dict] = {}
        self._json: dict[int, str] = {}

    def feed(self, name: str, data: dict) -> None:
        kind = name or data.get("type") or ""
        if kind == "message_start":
            message = data.get("message") or {}
            self.reply.id = message.get("id")
            self.reply.model = message.get("model") or ""
            self.reply.usage = dict(message.get("usage") or {})
        elif kind == "content_block_start":
            index = int(data.get("index", 0))
            self._blocks[index] = dict(data.get("content_block") or {})
            self._json[index] = ""
        elif kind == "content_block_delta":
            self._delta(int(data.get("index", 0)), data.get("delta") or {})
        elif kind == "content_block_stop":
            self._finish(int(data.get("index", 0)))
        elif kind == "message_delta":
            delta = data.get("delta") or {}
            if "stop_reason" in delta:
                self.reply.stop_reason = delta.get("stop_reason")
            if "stop_sequence" in delta:
                self.reply.stop_sequence = delta.get("stop_sequence")
            self.reply.usage.update(data.get("usage") or {})

    def _delta(self, index: int, delta: dict) -> None:
        block = self._blocks.get(index)
        if block is None:
            return
        kind = delta.get("type")
        if kind == "text_delta":
            block["text"] = block.get("text", "") + (delta.get("text") or "")
        elif kind == "thinking_delta":
            block["thinking"] = block.get("thinking", "") + (delta.get("thinking") or "")
        elif kind == "signature_delta":
            block["signature"] = block.get("signature", "") + (delta.get("signature") or "")
        elif kind == "input_json_delta":
            self._json[index] = self._json.get(index, "") + (delta.get("partial_json") or "")
        elif kind == "citations_delta" and delta.get("citation") is not None:
            block.setdefault("citations", []).append(delta["citation"])

    def _finish(self, index: int) -> None:
        block = self._blocks.get(index)
        if block is None or block.get("type") not in JSON_BLOCKS:
            return
        raw = (self._json.get(index) or "").strip()
        if not raw:
            block["input"] = block.get("input") or {}
            return
        try:
            block["input"] = json.loads(raw)
        except ValueError:
            logger.warning("anthropic sent unparsable tool input: %s", short(raw, 300))
            block["input"] = {}

    def result(self) -> Reply:
        self.reply.content = [self._blocks[i] for i in sorted(self._blocks)]
        return self.reply


async def _lines(stream) -> AsyncIterator[bytes]:
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


async def _events(stream) -> AsyncIterator[tuple[str, dict]]:
    name = ""
    async for raw in _lines(stream):
        line = raw.decode("utf-8", "replace")
        if not line:
            name = ""
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                logger.warning("anthropic sent unparsable sse data: %s", short(payload, 300))
                continue
            yield name or str(data.get("type") or ""), data


def _failure(status: int, raw: bytes, request_id: str | None, retry_after: str | None) -> ApiError:
    kind = "http_error"
    message = short(raw.decode("utf-8", "replace"), 500)
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            kind = error.get("type") or kind
            message = error.get("message") or message
    wait = None
    if retry_after and retry_after.strip().isdigit():
        wait = float(retry_after.strip())
    return ApiError(status, kind, message, request_id, wait)


async def _read(stream, on_event: Callable[[str, dict], None] | None) -> Reply:
    builder = Builder()
    async for name, data in _events(stream):
        if on_event is not None:
            on_event(name, data)
        if name == "error":
            error = data.get("error") or {}
            raise ApiError(
                200, error.get("type") or "api_error", error.get("message") or "stream failed"
            )
        builder.feed(name, data)
    return builder.result()


async def _once(
    credential: AnthropicCredential,
    body: dict,
    attempt: int,
    on_event: Callable[[str, dict], None] | None,
) -> Reply:
    http = await session()
    url = settings.anthropic_api_url.rstrip("/") + PATH
    timeout = aiohttp.ClientTimeout(
        total=settings.anthropic_timeout,
        connect=settings.anthropic_connect_timeout,
        sock_read=settings.anthropic_read_timeout,
    )
    started = time.perf_counter()
    with telemetry.span(
        "anthropic POST /v1/messages",
        kind=telemetry.CLIENT,
        attributes={
            attrs.HTTP_METHOD: "POST",
            attrs.HTTP_URL: url,
            attrs.SERVER_ADDRESS: urlparse(url).hostname,
            attrs.GEN_AI_SYSTEM: "anthropic",
            attrs.GEN_AI_MODEL: body.get("model"),
            attrs.ATTEMPT: attempt if attempt > 1 else None,
        },
    ) as span:
        try:
            async with http.post(
                url, headers=headers(credential), json=body, timeout=timeout
            ) as response:
                request_id = response.headers.get("request-id")
                telemetry.set_attrs(
                    span, {attrs.HTTP_STATUS: response.status, attrs.REQUEST_ID: request_id}
                )
                if response.status >= 400:
                    raise _failure(
                        response.status,
                        await response.read(),
                        request_id,
                        response.headers.get("retry-after"),
                    )
                reply = await _read(response.content, on_event)
        except TimeoutError as e:
            raise ApiError(
                0, "timeout_error", f"no answer in {settings.anthropic_timeout:.0f}s"
            ) from e
        except aiohttp.ClientError as e:
            raise ApiError(0, "network_error", f"{type(e).__name__}: {e}") from e
        telemetry.set_attrs(
            span,
            {
                attrs.GEN_AI_INPUT_TOKENS: reply.usage.get("input_tokens"),
                attrs.GEN_AI_OUTPUT_TOKENS: reply.usage.get("output_tokens"),
                "gen_ai.usage.cache_read_input_tokens": reply.usage.get("cache_read_input_tokens"),
                "gen_ai.usage.cache_creation_input_tokens": reply.usage.get(
                    "cache_creation_input_tokens"
                ),
                attrs.GEN_AI_FINISH_REASONS: [reply.stop_reason] if reply.stop_reason else None,
                attrs.BLOCKS: len(reply.content),
            },
        )
    logger.info(
        "anthropic %s stop=%s in=%s cached=%s written=%s out=%s (%.0fms)",
        reply.model or body.get("model"),
        reply.stop_reason,
        reply.usage.get("input_tokens"),
        reply.usage.get("cache_read_input_tokens"),
        reply.usage.get("cache_creation_input_tokens"),
        reply.usage.get("output_tokens"),
        (time.perf_counter() - started) * 1000,
    )
    return reply


async def send(
    credential: AnthropicCredential,
    body: dict,
    *,
    on_event: Callable[[str, dict], None] | None = None,
) -> Reply:
    delay = settings.anthropic_retry_base
    for attempt in range(1, settings.anthropic_retries + 1):
        try:
            return await _once(credential, body, attempt, on_event)
        except ApiError as e:
            if not e.retryable or attempt >= settings.anthropic_retries:
                raise
            wait = min(e.retry_after or delay, settings.anthropic_retry_max)
            telemetry.event(
                "anthropic.retry",
                {"attempt": attempt, "status": e.status, "kind": e.kind, "sleep_sec": wait},
            )
            logger.warning("anthropic %s, retrying in %.1fs", e.describe(), wait)
            await asyncio.sleep(wait)
            delay *= 2
    raise ApiError(0, "api_error", "retries exhausted")
