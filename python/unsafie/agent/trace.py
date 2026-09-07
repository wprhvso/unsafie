import logging

from unsafie import telemetry
from unsafie.agent import live as stream
from unsafie.agent.live import Live
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)

CALL_BLOCKS = ("tool_use", "server_tool_use")
THINKING_BLOCKS = ("thinking", "redacted_thinking")
KNOWN_BLOCKS = ("text", *THINKING_BLOCKS, *CALL_BLOCKS)
LIST_LIMIT = 200


def log_reply(reply, prefix: str) -> None:
    logger.info(
        "%s model=%s stop=%s blocks=%s",
        prefix,
        reply.model,
        reply.stop_reason,
        len(reply.content),
    )
    for index, block in enumerate(reply.content):
        kind = block.get("type")
        if kind == "text":
            logger.info("%s block[%s] text: %s", prefix, index, short(block.get("text")))
        elif kind in THINKING_BLOCKS:
            logger.debug("%s block[%s] thinking: %s", prefix, index, short(block.get("thinking")))
        elif kind in CALL_BLOCKS:
            logger.info(
                "%s block[%s] %s id=%s name=%s input=%s",
                prefix,
                index,
                kind,
                block.get("id"),
                block.get("name"),
                short(block.get("input")),
            )
        else:
            logger.debug("%s block[%s] %s: %s", prefix, index, kind, short(block))


def shrink(value, limit: int):
    """Keep the shape of a tool argument tree, cut the strings inside it."""
    if isinstance(value, str):
        body, cut = stream.clip(value, limit)
        return f"{body}…(+{cut} chars)" if cut else body
    if isinstance(value, dict):
        return {key: shrink(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        head = [shrink(item, limit) for item in value[:LIST_LIMIT]]
        if len(value) > LIST_LIMIT:
            head.append(f"…(+{len(value) - LIST_LIMIT} more)")
        return head
    return value


def _output(content) -> list[dict]:
    out: list[dict] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            body, cut = stream.clip(block.get("text") or "")
            item: dict = {"type": "text", "text": body}
            if cut:
                item["cut"] = cut
            out.append(item)
        elif kind == "image":
            source = block.get("source") or {}
            data = source.get("data") or ""
            item = {"type": "image", "media_type": source.get("media_type"), "size": len(data)}
            if settings.live_images and 0 < len(data) <= settings.live_image_bytes:
                item["data"] = data
            out.append(item)
        else:
            out.append({"type": kind or "unknown"})
    return out


def _block(block: dict) -> dict:
    kind = block.get("type")
    item: dict = {"type": kind}
    if kind in CALL_BLOCKS:
        item["id"] = block.get("id")
        item["name"] = block.get("name")
    elif kind == "text":
        item["chars"] = len(block.get("text") or "")
    elif kind == "thinking":
        item["chars"] = len(block.get("thinking") or "")
        # display=updates gives back an empty thinking field; say so instead of
        # showing an empty card.
        item["hidden"] = not item["chars"]
    elif kind == "redacted_thinking":
        item["hidden"] = True
    return item


class Recorder:
    """Writes a step into the log, the trace and — when someone is watching — the live stream."""

    def __init__(self, prefix: str, live: Live | None = None) -> None:
        self.prefix = prefix
        self.live = live
        self.steps = 0

    def request(self, step: int, messages: int, tools: int) -> None:
        self.steps = step
        logger.info("%s step=%s messages=%s tools=%s", self.prefix, step, messages, tools)
        if self.live is not None:
            self.live.emit("step.start", step=step, messages=messages, tools=tools)

    def raw(self, name: str, data: dict) -> None:
        """Every server-sent event of the model stream, as it arrives."""
        if self.live is None:
            return
        kind = name or str(data.get("type") or "")
        if kind == "message_start":
            message = data.get("message") or {}
            self.live.emit(
                "step.model",
                step=self.steps,
                id=message.get("id"),
                model=message.get("model"),
                usage=message.get("usage") or {},
            )
        elif kind == "content_block_start":
            block = data.get("content_block") or {}
            payload = {
                "step": self.steps,
                "index": int(data.get("index", 0)),
                "type": block.get("type"),
                "id": block.get("id"),
                "name": block.get("name"),
            }
            if block.get("type") not in KNOWN_BLOCKS:
                # Server-side tool results and anything the API grows later arrive
                # whole, with no deltas: carry the block itself so the page can
                # still show what came back.
                payload["block"] = shrink(block, settings.live_max_text)
            self.live.emit("block.open", **payload)
        elif kind == "content_block_delta":
            self._delta(int(data.get("index", 0)), data.get("delta") or {})
        elif kind == "content_block_stop":
            self.live.emit("block.close", step=self.steps, index=int(data.get("index", 0)))
        elif kind == "error":
            error = data.get("error") or {}
            self.failed(short(error.get("message") or "stream failed", 500), error.get("type"))

    def _delta(self, index: int, delta: dict) -> None:
        assert self.live is not None
        kind = delta.get("type")
        if kind == "text_delta":
            self.live.append("block.text", self.steps, index, delta.get("text") or "")
        elif kind == "thinking_delta":
            self.live.append("block.think", self.steps, index, delta.get("thinking") or "")
        elif kind == "input_json_delta":
            self.live.append("block.args", self.steps, index, delta.get("partial_json") or "")

    def reply(self, reply) -> None:
        log_reply(reply, f"{self.prefix} step#{self.steps}")
        if self.live is not None:
            self.live.emit(
                "step.end",
                step=self.steps,
                model=reply.model,
                stop_reason=reply.stop_reason,
                usage=reply.usage,
                blocks=[_block(b) for b in reply.content],
            )

    def tool_started(self, call_id: str, name: str, args: dict) -> None:
        if self.live is not None:
            self.live.emit(
                "tool.start",
                step=self.steps,
                call_id=call_id,
                name=name,
                input=shrink(args, settings.live_max_text),
            )

    def tool_finished(self, call_id: str, name: str, result: dict, ms: float) -> None:
        if self.live is not None:
            self.live.emit(
                "tool.end",
                step=self.steps,
                call_id=call_id,
                name=name,
                ok=not result.get("is_error"),
                ms=round(ms, 1),
                output=_output(result.get("content")),
            )

    def note(self, name: str, attributes: dict | None = None) -> None:
        telemetry.event(name, attributes)
        if self.live is not None:
            self.live.emit("note", step=self.steps, name=name, attributes=attributes or {})

    def failed(self, message: str, kind: str | None = None) -> None:
        if self.live is not None:
            self.live.emit("error", step=self.steps, type=kind, message=message)
