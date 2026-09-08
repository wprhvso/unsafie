
#!/usr/bin/env bash
set -euo pipefail

echo "==> Проверка рабочего каталога..."
if [ ! -d "python" ] || [ ! -d "svelte" ]; then
    echo "Ошибка: запустите apply.sh из корня репозитория unsafie (где есть папки python/ и svelte/)."
    exit 1
fi

echo "==> 1/7. Обновление python/unsafie/agent/request.py..."
cat << 'EOF' > python/unsafie/agent/request.py
import logging
from typing import Any

from unsafie.settings import settings

logger = logging.getLogger(__name__)

SAFETY_CATEGORIES = (
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
)


def safety_settings() -> list[dict[str, str]]:
    threshold = settings.gemini_safety_threshold
    return [{"category": category, "threshold": threshold} for category in SAFETY_CATEGORIES]


def generation_config(effort: str | None, max_tokens: int) -> dict[str, Any]:
    level = (effort or settings.gemini_thinking_level).lower()
    return {
        "maxOutputTokens": max_tokens,
        "thinkingConfig": {
            "thinkingLevel": level,
            "includeThoughts": True,
        },
    }


def system_instruction(prompt: str) -> dict[str, Any]:
    return {"parts": [{"text": prompt}]}


def reminder(text: str) -> str:
    return f"<system-reminder>\n{text}\n</system-reminder>"


def user(prompt: str, context: str | None = None) -> dict[str, Any]:
    text = f"{reminder(context)}\n\n{prompt}" if context else prompt
    return {"role": "user", "content": text}


def _extract_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({"text": item})
        elif isinstance(item, dict):
            # Сохраняем исходные части Gemini (рассуждения и сигнатуры) для сохранения контекста в истории
            if "thought" in item or "thoughtSignature" in item or "signature" in item:
                part_dict: dict[str, Any] = {}
                if "text" in item and item["text"]:
                    part_dict["text"] = item["text"]
                if item.get("thought") is True:
                    part_dict["thought"] = True
                sig = item.get("thoughtSignature") or item.get("signature")
                if sig:
                    part_dict["thoughtSignature"] = sig
                if part_dict:
                    parts.append(part_dict)
                continue

            item_type = item.get("type")
            if item_type == "text":
                text = item.get("text")
                if text:
                    parts.append({"text": text})
            elif item_type == "image":
                source = item.get("source") or {}
                if source.get("type") == "base64" and source.get("data"):
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": source.get("media_type") or "image/png",
                                "data": source.get("data"),
                            }
                        }
                    )
            elif "text" in item:
                parts.append({"text": str(item["text"])})
    return parts


def format_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []

    for msg in messages:
        raw_role = msg.get("role")
        role = "model" if raw_role in ("assistant", "model") else "user"
        parts = _extract_parts(msg.get("content"))
        if not parts:
            continue

        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})

    return contents


def build(
    *,
    model: str,
    prompt: str,
    messages: list[dict[str, Any]],
    effort: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    limit = max_tokens or settings.gemini_max_output_tokens
    return {
        "contents": format_contents(messages),
        "systemInstruction": system_instruction(prompt),
        "generationConfig": generation_config(effort, limit),
        "safetySettings": safety_settings(),
    }
EOF

echo "==> 2/7. Обновление python/unsafie/agent/client.py..."
cat << 'EOF' > python/unsafie/agent/client.py
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

    @property
    def content(self) -> list[dict]:
        return self.raw_parts if self.raw_parts else ([{"type": "text", "text": self.text}] if self.text else [])

    @property
    def calls(self) -> list[dict]:
        return []

    def as_message(self) -> dict:
        # Сохраняем raw_parts (мысли + сигнатуры + код), обеспечивая сохранение цепочки рассуждений в многоходовом диалоге
        return {"role": "assistant", "content": self.raw_parts if self.raw_parts else self.text}


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
EOF

echo "==> 3/7. Обновление python/unsafie/agent/trace.py..."
cat << 'EOF' > python/unsafie/agent/trace.py
import logging

from unsafie import telemetry
from unsafie.agent import live as stream
from unsafie.agent.live import Live
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)


def log_reply(reply, prefix: str) -> None:
    logger.info(
        "%s model=%s stop=%s text_len=%s thoughts_len=%s signatures=%s",
        prefix,
        reply.model,
        reply.stop_reason,
        len(reply.text),
        len(reply.thoughts),
        len(reply.thought_signatures),
    )
    if reply.thoughts:
        logger.debug("%s thoughts: %s", prefix, short(reply.thoughts))
    if reply.text:
        logger.info("%s text: %s", prefix, short(reply.text))


class Recorder:
    def __init__(self, prefix: str, live: Live | None = None) -> None:
        self.prefix = prefix
        self.live = live
        self.steps = 0

    def request(self, step: int, messages: int, tools: int) -> None:
        self.steps = step
        logger.info("%s step=%s messages=%s", self.prefix, step, messages)
        if self.live is not None:
            self.live.emit("step.start", step=step, messages=messages, tools=tools)

    def raw(self, name: str, data: dict) -> None:
        if self.live is None:
            return
        if name == "message_start":
            self.live.emit(
                "step.model",
                step=self.steps,
                model=data.get("model"),
            )
        elif name == "thought_delta":
            thought = data.get("thought") or ""
            self.live.append("block.think", self.steps, 0, thought)
        elif name == "thought_signature":
            signature = data.get("signature") or ""
            self.live.emit("block.signature", step=self.steps, signature=signature)
        elif name == "text_delta":
            text = data.get("text") or ""
            self.live.append("block.text", self.steps, 0, text)
        elif name == "message_delta":
            self.live.emit(
                "step.usage",
                step=self.steps,
                usage=data.get("usage") or {},
                stop_reason=data.get("stop_reason"),
            )
        elif name == "error":
            error = data.get("error") or {}
            self.failed(short(error.get("message") or "stream failed", 500), error.get("type"))

    def reply(self, reply) -> None:
        log_reply(reply, f"{self.prefix} step#{self.steps}")
        if self.live is not None:
            blocks = []
            if reply.thoughts:
                blocks.append({"type": "thinking", "chars": len(reply.thoughts)})
            if reply.text:
                blocks.append({"type": "text", "chars": len(reply.text)})
            self.live.emit(
                "step.end",
                step=self.steps,
                model=reply.model,
                stop_reason=reply.stop_reason,
                usage=reply.usage,
                blocks=blocks,
            )

    def code_started(self, index: int, code: str, machine: str = "") -> None:
        if self.live is not None:
            self.live.emit(
                "code.start",
                step=self.steps,
                index=index,
                code=code,
                machine=machine,
            )

    def code_finished(
        self,
        index: int,
        machine: str,
        exit_code: int | None,
        output: str,
        seconds: float,
        error: str | None = None,
        images: list[dict] | None = None,
    ) -> None:
        if self.live is not None:
            self.live.emit(
                "code.end",
                step=self.steps,
                index=index,
                machine=machine,
                exit_code=exit_code,
                output=output,
                seconds=round(seconds, 3),
                error=error,
                images=images or [],
            )

    def tool_started(self, call_id: str, name: str, args: dict) -> None:
        # Обратная совместимость
        pass

    def tool_finished(self, call_id: str, name: str, result: dict, ms: float) -> None:
        # Обратная совместимость
        pass

    def note(self, name: str, attributes: dict | None = None) -> None:
        telemetry.event(name, attributes)
        if self.live is not None:
            self.live.emit("note", step=self.steps, name=name, attributes=attributes or {})

    def failed(self, message: str, kind: str | None = None) -> None:
        if self.live is not None:
            self.live.emit("error", step=self.steps, type=kind, message=message)
EOF

echo "==> 4/7. Обновление python/unsafie/agent/blocks.py..."
cat << 'EOF' > python/unsafie/agent/blocks.py
import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field

from unsafie.agent import live
from unsafie.agent.session import Ctx
from unsafie.errors import OpsError
from unsafie.log import short
from unsafie.mime import human_size, image_block, image_problem, sniff_mime
from unsafie.pool import blobs, channel, leases
from unsafie.settings import settings
from unsafie_wire import markers

logger = logging.getLogger(__name__)

NAG_EVERY = 60.0
REASON_LIMIT = 300


@dataclass
class Block:
    index: int
    code: str
    started_at: float = field(default_factory=time.monotonic)
    machine: str = ""
    exit_code: int | None = None
    output: str = ""
    seconds: float = 0.0
    truncated: bool = False
    error: str | None = None
    images: list[dict] = field(default_factory=list)
    sent: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def failed(self) -> bool:
        return bool(self.error) or not self.ok

    def reason(self) -> str:
        if self.error:
            return self.error[:REASON_LIMIT]
        lines = [line for line in (self.output or "").strip().splitlines() if line.strip()]
        return lines[-1][:REASON_LIMIT] if lines else ""

    def heading(self) -> str:
        where = self.machine or "no machine"
        if self.error:
            return f"[block {self.index}] {where}: {self.error}"
        if self.exit_code is None:
            return f"[block {self.index}] {where}: never came back, {self.seconds:.0f}s"
        if self.ok:
            return f"[block {self.index}] {where} · ok in {self.seconds:.1f}s"
        tail = self.reason()
        head = f"[block {self.index}] {where} · raised in {self.seconds:.1f}s"
        return f"{head}: {tail}" if tail else head


class Runner:
    def __init__(self, ctx: Ctx, recorder) -> None:
        self.ctx = ctx
        self.recorder = recorder
        self.blocks: list[Block] = []
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    @property
    def count(self) -> int:
        return len(self.blocks)

    def start(self, code: str) -> Block:
        index = len(self.blocks) + 1
        block = Block(index=index, code=code)
        self.blocks.append(block)
        self.recorder.code_started(index, code)
        task = asyncio.create_task(
            self._run(block), name=f"python:{self.ctx.turn_id}:{block.index}"
        )
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return block

    async def _nag(self, block: Block) -> None:
        waited = 0.0
        while True:
            await asyncio.sleep(NAG_EVERY)
            waited += NAG_EVERY
            logger.warning(
                "%s python block %s on %s has been running for %.0fs",
                self.ctx.prefix,
                block.index,
                block.machine or "-",
                waited,
            )
            live.emit(
                self.ctx.turn_id,
                "note",
                name="unsafie.block_slow",
                attributes={
                    "index": block.index,
                    "machine": block.machine,
                    "seconds": int(waited),
                    "timeout": settings.pool_block_timeout,
                },
            )

    async def _run(self, block: Block) -> None:
        async with self.lock:
            try:
                machine = await leases.ensure(
                    self.ctx.user_id, self.ctx.chat_id, self.ctx.turn_id, self.ctx.bot_id
                )
            except OpsError as refused:
                block.error = str(refused)
                block.seconds = time.monotonic() - block.started_at
                self._finished(block)
                return
            block.machine = machine.alias or machine.name
            watch = asyncio.create_task(
                self._nag(block), name=f"python-slow:{self.ctx.turn_id}:{block.index}"
            )
            try:
                result = await channel.run_python(
                    machine.name,
                    block.code,
                    user_id=self.ctx.user_id,
                    turn_id=self.ctx.turn_id,
                    timeout=settings.pool_block_timeout,
                )
            except asyncio.CancelledError:
                block.error = "stopped by the user"
                block.seconds = time.monotonic() - block.started_at
                self._finished(block)
                raise
            except Exception as broken:
                block.error = f"{type(broken).__name__}: {broken}"
                block.seconds = time.monotonic() - block.started_at
                logger.exception("%s python block %s could not run", self.ctx.prefix, block.index)
                self._finished(block)
                return
            finally:
                watch.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watch
            body, found = markers.split(result.output)
            block.output = body
            block.exit_code = result.exit_code
            block.seconds = result.seconds
            block.truncated = result.truncated
            await self._decorate(block, found)
            self._finished(block)

    async def _decorate(self, block: Block, found: list[markers.Block]) -> None:
        for item in found:
            if item.kind == markers.BlockKind.SENT:
                block.sent = True
            elif item.kind == markers.BlockKind.IMAGE:
                rendered = await self._image(block, item)
                if rendered is not None:
                    block.images.append(rendered)
            elif item.kind in (markers.BlockKind.NOTE, markers.BlockKind.PROGRESS):
                live.emit(self.ctx.turn_id, "note", text=str(item.data.get("text") or ""))
            elif item.kind == markers.BlockKind.LINK:
                block.output += f"\n{item.data.get('title') or 'link'}: {item.data.get('url')}"
            elif item.kind == markers.BlockKind.RESULT:
                block.output += f"\nresult: {item.data.get('value')}"
            elif item.kind == markers.BlockKind.ERROR:
                block.output += f"\nerror: {item.data.get('message')}"

    async def _image(self, block: Block, item: markers.Block) -> dict | None:
        key = str(item.data.get("blob") or "")
        if not key:
            return None
        data = await blobs.get(self.ctx.user_id, key)
        if data is None:
            block.output += f"\n[image {key} was not stored, nothing to show]"
            return None
        mime = str(item.data.get("mime") or sniff_mime(data, key))
        problem = image_problem(data, mime)
        if problem:
            block.output += f"\n[image {key} not attached: {problem}]"
            return None
        live.emit(self.ctx.turn_id, "note", text=f"image {key} ({human_size(len(data))})")
        return image_block(data, mime)

    def _body(self, block: Block, limit: int | None = None) -> str:
        text = block.heading()
        if block.truncated:
            text += f" (output cut at {human_size(settings.pool_max_output)})"
        text = f"{text}\n{block.output.strip() or '(no output)'}"
        if limit:
            text = short(text, limit)
        return text

    def _finished(self, block: Block) -> None:
        self.recorder.code_finished(
            index=block.index,
            machine=block.machine or "-",
            exit_code=block.exit_code,
            output=self._body(block, limit=8000),
            seconds=block.seconds,
            error=block.error,
            images=block.images,
        )
        logger.info(
            "%s python block %s on %s: %s",
            self.ctx.prefix,
            block.index,
            block.machine or "-",
            block.error or f"exit={block.exit_code} in {block.seconds:.1f}s",
        )

    async def settle(self) -> list[dict]:
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        return self.content()

    def content(self) -> list[dict]:
        if not self.blocks:
            return []
        parts: list[dict] = []
        for block in self.blocks:
            parts.append({"type": "text", "text": self._body(block)})
            if not block.failed and block.images:
                parts.extend(block.images)
        return parts

    @property
    def replied(self) -> bool:
        return any(block.sent for block in self.blocks)
EOF

echo "==> 5/7. Обновление svelte/src/lib/components/live/icons.js..."
cat << 'EOF' > svelte/src/lib/components/live/icons.js
export const ICONS = {
  prompt: ['M20 21v-1a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v1', 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z'],
  think: ['M13 2 3 14h9l-1 8 10-12h-9l1-8z'],
  text: ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
  code: ['M16 18l6-6-6-6', 'M8 6l-6 6 6 6'],
  reply: ['M22 2 11 13', 'M22 2l-7 20-4-9-9-4 20-7z'],
  note: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 16v-4', 'M12 8h.01'],
  error: [
    'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z',
    'M12 9v4',
    'M12 17h.01'
  ],
  step: ['M12 2 2 7l10 5 10-5-10-5z', 'M2 17l10 5 10-5', 'M2 12l10 5 10-5'],
  attempt: [
    'M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z',
    'M9 9h6v6H9z',
    'M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3'
  ],
  end: ['M22 11.08V12a10 10 0 1 1-5.93-9.14', 'M22 4 12 14.01l-3-3'],
  zoomIn: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'M21 21l-4.35-4.35', 'M11 8v6M8 11h6'],
  zoomOut: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'M21 21l-4.35-4.35', 'M8 11h6'],
  down: ['M12 5v14', 'M19 12l-7 7-7-7'],
  expand: ['M4 9V4h5', 'M20 15v5h-5', 'M4 4l6 6', 'M20 20l-6-6'],
  collapse: ['M9 4v5H4', 'M15 20v-5h5', 'M4 9l6-6', 'M20 15l-6 6'],
  copy: [
    'M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z',
    'M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1'
  ],
  check: ['M20 6 9 17l-5-5']
};
EOF

echo "==> 6/7. Обновление svelte/src/lib/live/timeline.svelte.js..."
cat << 'EOF' > svelte/src/lib/live/timeline.svelte.js
import { UNITS_PER_USD } from '../format.js';
import { contextLimit, contextOf, costOf } from './pricing.js';

const USAGE = [
  'input_tokens',
  'output_tokens',
  'cache_read_input_tokens',
  'cache_creation_input_tokens'
];

function merge(into, usage) {
  for (const key of USAGE) {
    const value = usage?.[key];
    if (typeof value === 'number') into[key] = (into[key] ?? 0) + value;
  }
}

export function timeline() {
  const state = $state({
    items: [],
    turn: null,
    model: null,
    effort: null,
    steps: 0,
    calls: 0,
    cost: 0,
    settled: 0,
    pending: 0,
    charge: 0,
    spent: 0,
    ratio: null,
    budget: null,
    balance: null,
    usage: {},
    context: 0,
    contextPeak: 0,
    contextLimit: contextLimit(null),
    startedAt: null,
    endedAt: null,
    outcome: null
  });

  let blocks = new Map();
  let codeBlocks = new Map();
  let steps = new Map();
  let attempts = [];
  let balanceStart = null;

  const at = (frame) => frame.at ?? null;

  function seeContext(usage, model) {
    const size = contextOf(usage);
    if (!size) return;
    state.context = size;
    state.contextPeak = Math.max(state.contextPeak, size);
    state.contextLimit = contextLimit(model ?? state.model);
  }

  function total() {
    state.cost = state.settled + state.pending;
    state.spent = state.charge / UNITS_PER_USD + state.pending * (state.ratio ?? 1);
    if (balanceStart !== null) state.balance = Math.max(balanceStart - state.spent, 0);
  }

  function push(item) {
    state.items.push(item);
    return state.items[state.items.length - 1];
  }

  function ensureBlock(step, type) {
    const k = `${step}:${type}`;
    let item = blocks.get(k);
    if (!item) {
      item = push({
        id: crypto.randomUUID(),
        at: new Date().toISOString(),
        step,
        type,
        text: '',
        signature: null,
        streaming: true
      });
      blocks.set(k, item);
    }
    return item;
  }

  function apply(frame) {
    const data = frame.data ?? {};
    const when = at(frame) ?? new Date().toISOString();

    switch (frame.kind) {
      case 'turn.start':
        state.turn = { id: data.turn_id, chat: data.chat_id, resumed: data.resumed ?? 0 };
        state.startedAt = when;
        push({ id: frame.id, at: when, type: 'prompt', text: data.prompt ?? '' });
        break;

      case 'attempt.start': {
        state.model = data.model ?? state.model;
        state.effort = data.effort ?? state.effort;
        state.ratio = typeof data.ratio === 'number' ? data.ratio : state.ratio;
        if (typeof data.budget_units === 'number')
          state.budget = data.budget_units / UNITS_PER_USD + state.spent;
        if (typeof data.balance_units === 'number')
          balanceStart = data.balance_units / UNITS_PER_USD;
        state.contextLimit = contextLimit(state.model);
        total();
        const item = push({
          id: frame.id,
          at: when,
          type: 'attempt',
          attempt: data.attempt,
          model: data.model,
          effort: data.effort,
          budget: data.budget_usd
        });
        attempts.push(item);
        break;
      }

      case 'attempt.end': {
        const item = attempts[attempts.length - 1];
        if (item) {
          item.status = data.status;
          item.cost = data.cost_usd;
          item.stop = data.stop_reason;
          item.error = data.error;
        }
        state.settled =
          typeof data.total_cost === 'number'
            ? data.total_cost
            : state.settled + (data.cost_usd ?? 0);
        state.charge =
          typeof data.total_charge === 'number'
            ? data.total_charge
            : state.charge + (data.charge ?? 0);
        state.pending = 0;
        total();
        break;
      }

      case 'step.start': {
        state.steps = Math.max(state.steps, data.step ?? 0);
        const item = push({
          id: frame.id,
          at: when,
          type: 'step',
          step: data.step,
          messages: data.messages
        });
        steps.set(data.step, item);
        break;
      }

      case 'step.model': {
        const item = steps.get(data.step);
        if (item) item.model = data.model;
        state.model = data.model ?? state.model;
        state.contextLimit = contextLimit(state.model);
        break;
      }

      case 'charge': {
        if (typeof data.total === 'number') state.charge = data.total;
        if (typeof data.cost_usd === 'number') state.settled = data.cost_usd;
        state.pending = 0;
        if (typeof data.balance === 'number')
          balanceStart = (data.balance + state.charge) / UNITS_PER_USD;
        total();
        break;
      }

      case 'step.end': {
        const item = steps.get(data.step);
        if (item) {
          item.model = data.model ?? item.model;
          item.stop = data.stop_reason;
          item.usage = data.usage ?? {};
          item.endedAt = when;
        }
        merge(state.usage, data.usage);
        state.pending += costOf(data.usage, data.model ?? state.model);
        seeContext(data.usage, data.model);
        total();

        const thinkItem = blocks.get(`${data.step}:think`);
        if (thinkItem) thinkItem.streaming = false;
        const textItem = blocks.get(`${data.step}:text`);
        if (textItem) textItem.streaming = false;
        break;
      }

      case 'block.think': {
        const item = ensureBlock(data.step ?? state.steps, 'think');
        item.text += (data.text ?? '');
        break;
      }

      case 'block.signature': {
        const item = ensureBlock(data.step ?? state.steps, 'think');
        item.signature = data.signature;
        break;
      }

      case 'block.text': {
        const item = ensureBlock(data.step ?? state.steps, 'text');
        item.text += (data.text ?? '');
        break;
      }

      case 'code.start': {
        state.calls += 1;
        const item = push({
          id: frame.id,
          at: when,
          type: 'code',
          step: data.step ?? state.steps,
          index: data.index,
          code: data.code,
          machine: data.machine || 'sandbox',
          status: 'running',
          output: '',
          error: null,
          exit_code: null,
          seconds: null,
          images: []
        });
        codeBlocks.set(data.index, item);
        break;
      }

      case 'code.end': {
        const item = codeBlocks.get(data.index);
        if (item) {
          item.status = (data.exit_code === 0 && !data.error) ? 'ok' : 'failed';
          item.machine = data.machine || item.machine;
          item.exit_code = data.exit_code;
          item.output = data.output || '';
          item.error = data.error;
          item.seconds = data.seconds;
          item.images = data.images ?? [];
        }
        break;
      }

      case 'reply.sent':
        push({
          id: frame.id,
          at: when,
          type: 'reply',
          text: data.text ?? '',
          kind: data.kind,
          messageIds: data.message_ids ?? []
        });
        break;

      case 'note':
        push({ id: frame.id, at: when, type: 'note', name: data.name, attributes: data.attributes });
        break;

      case 'error':
        push({ id: frame.id, at: when, type: 'error', message: data.message, errorType: data.type });
        break;

      case 'turn.end':
        state.endedAt = when;
        state.outcome = data.status;
        if (typeof data.charge === 'number') state.charge = data.charge;
        if (typeof data.cost_usd === 'number') state.settled = data.cost_usd;
        state.pending = 0;
        total();
        push({
          id: frame.id,
          at: when,
          type: 'end',
          status: data.status,
          steps: data.steps,
          cost: data.cost_usd,
          charge: data.charge,
          note: data.note
        });
        break;

      default:
        break;
    }
  }

  function reset() {
    state.items = [];
    state.usage = {};
    state.steps = 0;
    state.calls = 0;
    state.cost = 0;
    state.settled = 0;
    state.pending = 0;
    state.charge = 0;
    state.spent = 0;
    state.balance = null;
    balanceStart = null;
    state.context = 0;
    state.contextPeak = 0;
    state.outcome = null;
    state.endedAt = null;
    blocks.clear();
    codeBlocks.clear();
    steps.clear();
    attempts = [];
  }

  return { state, apply, reset };
}
EOF

echo "==> 7/7. Обновление svelte/src/lib/components/live/Entry.svelte..."
cat << 'EOF' > svelte/src/lib/components/live/Entry.svelte
<script>
  import { UNITS_PER_USD, short } from '$lib/format.js';
  import Copy from './Copy.svelte';
  import Icon from './Icon.svelte';
  import Markdown from './Markdown.svelte';

  let { item, open = false, ontoggle } = $props();

  const toggle = () => ontoggle?.(item.id);

  function clock(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(+date) ? '' : date.toLocaleTimeString(undefined, { hour12: false });
  }

  function took(seconds) {
    if (seconds === null || seconds === undefined) return '';
    return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${Number(seconds).toFixed(2)} s`;
  }
</script>

{#if item.type === 'step'}
  <div class="divider step">
    <Icon name="step" size={13} />
    <span class="label">Step {item.step}</span>
    <span class="line"></span>
    <time class="muted tiny">{clock(item.at)}</time>
  </div>

{:else if item.type === 'attempt'}
  <div class="divider attempt">
    <Icon name="attempt" size={13} />
    <span class="label">Attempt {item.attempt}</span>
    {#if item.model}<span class="chip mono">{item.model}</span>{/if}
    {#if item.effort}<span class="chip">effort {item.effort}</span>{/if}
    <span class="line"></span>
    <time class="muted tiny">{clock(item.at)}</time>
  </div>

{:else if item.type === 'think'}
  <article class="entry think" class:open class:busy={item.streaming}>
    <div class="rail">
      <span class="bead"><Icon name="think" size={12} /></span>
    </div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title">Reasoning</span>
        {#if item.signature}
          <span class="sig-pill" title="Cryptographic proof of internal reasoning state">
            🔒 Signed
          </span>
        {/if}
        <span class="spacer"></span>
        <span class="muted tiny nowrap">{item.text?.length?.toLocaleString() ?? 0} chars</span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>

      <div class="thought" class:clamped={!open}>
        {item.text || (item.streaming ? 'Thinking…' : 'No reasoning text.')}
      </div>

      {#if item.signature && open}
        <div class="signature-bar">
          <span class="muted tiny">Signature:</span>
          <code class="sig-preview" title={item.signature}>{item.signature.slice(0, 32)}…</code>
          <Copy text={item.signature} label="Copy Thought Signature" />
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'code'}
  <article class="entry code {item.status}" class:open>
    <div class="rail">
      <span class="bead code-bead"><Icon name="code" size={13} /></span>
    </div>

    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title mono">Python [#{item.index}]</span>
        <span class="machine-tag mono">{item.machine || 'sandbox'}</span>
        <span class="spacer"></span>
        <span class="status-tag {item.status}">
          {item.status === 'running' ? 'running…' : item.status === 'ok' ? 'ok' : `exit ${item.exit_code ?? 1}`}
        </span>
        {#if item.seconds !== null}
          <span class="muted tiny nowrap">{took(item.seconds)}</span>
        {/if}
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>

      <!-- Блок с исходным кодом Python -->
      <div class="code-box">
        <div class="box-head">
          <span class="muted tiny">Python Code</span>
          <Copy text={item.code} label="Copy Python Code" />
        </div>
        <pre class="source"><code>{item.code}</code></pre>
      </div>

      <!-- Консольный вывод REPL (stdout / stderr) -->
      {#if item.output || item.error || item.images?.length}
        <div class="output-box">
          <div class="box-head">
            <span class="muted tiny">Terminal Output</span>
            {#if item.output}<Copy text={item.output} label="Copy Output" />{/if}
          </div>

          {#if item.output}
            <pre class="terminal">{item.output}</pre>
          {/if}

          {#if item.error}
            <div class="error-box">{item.error}</div>
          {/if}

          {#if item.images?.length}
            <div class="images-grid">
              {#each item.images as img}
                <img src="data:{img.media_type || 'image/png'};base64,{img.data}" alt="Output plot" />
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'text' || item.type === 'reply'}
  <article class="entry {item.type}" class:open>
    <div class="rail">
      <span class="bead"><Icon name={item.type === 'reply' ? 'reply' : 'text'} size={12} /></span>
    </div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title">{item.type === 'reply' ? 'Sent to chat' : 'Model Output'}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>
      <div class="prose">
        <Markdown source={item.text} streaming={item.streaming} />
      </div>
      {#if open && item.type === 'reply' && item.messageIds?.length}
        <div class="details">
          <p class="muted tiny">Telegram message IDs: {item.messageIds.join(', ')}</p>
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'prompt'}
  <article class="entry prompt" class:open>
    <div class="rail"><span class="bead"><Icon name="prompt" size={12} /></span></div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title">User Prompt</span>
        <span class="sub">{short(item.text, 80)}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>
      {#if open}
        <div class="body">
          <pre class="source">{item.text}</pre>
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'note'}
  <article class="entry note" class:open>
    <div class="rail"><span class="bead"><Icon name="note" size={12} /></span></div>
    <div class="card">
      <button class="head" onclick={toggle} aria-expanded={open}>
        <span class="caret" class:open>▸</span>
        <span class="title">Note: {item.name}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </button>
      {#if open && item.attributes}
        <div class="body">
          <pre class="source">{JSON.stringify(item.attributes, null, 2)}</pre>
        </div>
      {/if}
    </div>
  </article>

{:else if item.type === 'error'}
  <article class="entry error bad open">
    <div class="rail"><span class="bead"><Icon name="error" size={12} /></span></div>
    <div class="card">
      <div class="head">
        <span class="title">Error</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </div>
      <div class="body error-box">{item.message}</div>
    </div>
  </article>

{:else if item.type === 'end'}
  <article class="entry end {item.status === 'ok' ? 'ok' : 'bad'}">
    <div class="rail"><span class="bead"><Icon name="end" size={12} /></span></div>
    <div class="card">
      <div class="head">
        <span class="title">Finished: {item.status}</span>
        <span class="spacer"></span>
        <time class="muted tiny nowrap">{clock(item.at)}</time>
      </div>
      <div class="body">
        <p class="small">
          {item.steps ?? 0} steps
          {#if item.charge} · ${(Number(item.charge) / UNITS_PER_USD).toFixed(4)} charged{/if}
          {#if item.cost} · ${Number(item.cost).toFixed(4)} API{/if}
        </p>
        {#if item.note}<pre class="source">{item.note}</pre>{/if}
      </div>
    </div>
  </article>
{/if}

<style>
  .divider {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 1rem 0 0.4rem;
    color: var(--muted);
  }
  .divider .label {
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text);
  }
  .divider .line {
    flex: 1;
    min-width: 1rem;
    height: 1px;
    background: var(--border);
  }
  .divider.attempt .label {
    color: var(--warn);
  }

  .chip {
    padding: 0.05rem 0.4rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.72rem;
    background: var(--panel);
  }

  .entry {
    display: grid;
    grid-template-columns: 1.6rem 1fr;
    gap: 0.5rem;
    margin: 0.4rem 0;
  }
  .rail {
    position: relative;
    display: flex;
    justify-content: center;
  }
  .rail::before {
    content: '';
    position: absolute;
    top: 0;
    bottom: -0.6rem;
    width: 1px;
    background: var(--border);
  }
  .bead {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.35rem;
    height: 1.35rem;
    margin-top: 0.35rem;
    border: 1px solid var(--border);
    border-radius: 50%;
    background: var(--bg);
    color: var(--muted);
  }

  .entry.code .code-bead {
    color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  }
  .entry.think .bead {
    color: var(--live-think, #8250df);
    border-color: color-mix(in srgb, var(--live-think, #8250df) 45%, var(--border));
  }
  .entry.reply .bead {
    color: var(--ok);
    border-color: color-mix(in srgb, var(--ok) 45%, var(--border));
  }
  .entry.error .bead,
  .entry.bad .bead {
    color: var(--bad);
    border-color: color-mix(in srgb, var(--bad) 45%, var(--border));
  }

  .entry.busy .bead {
    animation: pulse 1.4s ease-in-out infinite;
  }
  @keyframes pulse {
    50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 14%, transparent); }
  }

  .card {
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
    overflow: hidden;
    min-width: 0;
  }
  .entry.open .card,
  .card:hover {
    border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  }

  .head {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    width: 100%;
    padding: 0.45rem 0.6rem;
    border: 0;
    background: none;
    color: inherit;
    text-align: left;
    cursor: pointer;
    min-width: 0;
  }
  .head:hover {
    background: color-mix(in srgb, var(--accent) 5%, transparent);
  }
  .caret {
    color: var(--muted);
    font-size: 0.7rem;
    transition: transform 0.12s ease;
  }
  .caret.open {
    transform: rotate(90deg);
  }
  .title {
    font-weight: 600;
    font-size: 0.88rem;
    flex: 0 0 auto;
  }
  .sub {
    color: var(--muted);
    font-size: 0.82rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .spacer {
    flex: 1;
    min-width: 0.3rem;
  }

  .machine-tag {
    font-size: 0.72rem;
    padding: 0.05rem 0.35rem;
    border-radius: 4px;
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    color: var(--accent);
  }

  .status-tag {
    font-size: 0.72rem;
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    background: color-mix(in srgb, var(--muted) 15%, transparent);
    color: var(--muted);
  }
  .status-tag.ok {
    background: color-mix(in srgb, var(--ok) 16%, transparent);
    color: var(--ok);
  }
  .status-tag.failed {
    background: color-mix(in srgb, var(--bad) 16%, transparent);
    color: var(--bad);
  }
  .status-tag.running {
    background: color-mix(in srgb, var(--warn) 16%, transparent);
    color: var(--warn);
  }

  .sig-pill {
    font-size: 0.7rem;
    padding: 0.05rem 0.4rem;
    border-radius: 4px;
    background: color-mix(in srgb, var(--live-think, #8250df) 14%, transparent);
    color: var(--live-think, #8250df);
    border: 1px solid color-mix(in srgb, var(--live-think, #8250df) 30%, transparent);
  }

  .signature-bar {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.7rem;
    border-top: 1px dashed var(--border);
    background: var(--live-sunken);
  }
  .sig-preview {
    font-size: 0.75rem;
    color: var(--muted);
    background: none;
    padding: 0;
  }

  .thought {
    padding: 0.4rem 0.7rem 0.6rem;
    font-size: 0.84rem;
    line-height: 1.55;
    color: var(--muted);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-style: italic;
  }
  .thought.clamped {
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .code-box,
  .output-box {
    border-top: 1px solid var(--border);
  }

  .box-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.25rem 0.6rem;
    background: var(--live-sunken);
    border-bottom: 1px solid var(--border);
  }

  pre.source {
    margin: 0;
    padding: 0.6rem 0.7rem;
    background: transparent;
    font-size: 0.82rem;
    font-family: var(--mono);
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre;
  }

  pre.terminal {
    margin: 0;
    padding: 0.6rem 0.7rem;
    background: #0d1117;
    color: #c9d1d9;
    font-size: 0.82rem;
    font-family: var(--mono);
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    max-height: 28rem;
  }

  .error-box {
    padding: 0.5rem 0.7rem;
    color: var(--bad);
    font-size: 0.82rem;
    background: color-mix(in srgb, var(--bad) 10%, transparent);
    white-space: pre-wrap;
  }

  .images-grid {
    display: grid;
    gap: 0.5rem;
    padding: 0.6rem;
    background: #0d1117;
    border-top: 1px solid var(--border);
  }
  .images-grid img {
    max-width: 100%;
    border-radius: 4px;
    border: 1px solid #30363d;
  }

  .prose {
    padding: 0.4rem 0.7rem 0.6rem;
    font-size: 0.9rem;
    line-height: 1.55;
  }
  .body,
  .details {
    padding: 0.5rem 0.7rem;
    border-top: 1px solid var(--border);
  }

  .tiny { font-size: 0.73rem; }
  .small { font-size: 0.85rem; }
  .mono { font-family: var(--mono); }
  .nowrap { white-space: nowrap; }
</style>
EOF

echo "==> Проверка сборки фронтенда..."
if command -v npm >/dev/null 2>&1; then
    echo "==> Запуск npm run build в каталоге svelte/..."
    (cd svelte && npm run build)
    echo "==> Сборка фронтенда успешно завершена!"
else
    echo "==> npm не найден, соберите фронтенд вручную: (cd svelte && npm run build)"
fi

echo "=========================================================="
echo " Готово! Все изменения применены."
echo " 1. Включен includeThoughts в Gemini ThinkingConfig."
echo " 2. Добавлен сбор и трансляция thoughtSignature."
echo " 3. Устаревший код тул-коллов удален."
echo " 4. Внедрен полноценный Python REPL (код + терминал + вывод)."
echo "=========================================================="
