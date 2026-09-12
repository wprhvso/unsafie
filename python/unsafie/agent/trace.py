
from unsafie import telemetry
from unsafie.agent.live import Live
from unsafie.log import get_logger, short

logger = get_logger(__name__)


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
