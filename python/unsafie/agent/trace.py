import logging

from unsafie import telemetry
from unsafie.agent import live as stream
from unsafie.agent.live import Live
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)

LIST_LIMIT = 200


def log_reply(reply, prefix: str) -> None:
    logger.info(
        "%s model=%s stop=%s text_len=%s thoughts_len=%s",
        prefix,
        reply.model,
        reply.stop_reason,
        len(reply.text),
        len(reply.thoughts),
    )
    if reply.thoughts:
        logger.debug("%s thoughts: %s", prefix, short(reply.thoughts))
    if reply.text:
        logger.info("%s text: %s", prefix, short(reply.text))


def shrink(value, limit: int):
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
    if isinstance(content, str):
        body, cut = stream.clip(content)
        item = {"type": "text", "text": body}
        if cut:
            item["cut"] = cut
        return [item]
    out: list[dict] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            body, cut = stream.clip(block.get("text") or "")
            item = {"type": "text", "text": body}
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
                output=_output(result.get("output")),
            )

    def note(self, name: str, attributes: dict | None = None) -> None:
        telemetry.event(name, attributes)
        if self.live is not None:
            self.live.emit("note", step=self.steps, name=name, attributes=attributes or {})

    def failed(self, message: str, kind: str | None = None) -> None:
        if self.live is not None:
            self.live.emit("error", step=self.steps, type=kind, message=message)
