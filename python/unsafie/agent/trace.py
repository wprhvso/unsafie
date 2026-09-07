import logging

from unsafie import telemetry
from unsafie.log import short

logger = logging.getLogger(__name__)

CALL_BLOCKS = ("tool_use", "server_tool_use")
THINKING_BLOCKS = ("thinking", "redacted_thinking")


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


class Recorder:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.steps = 0

    def request(self, step: int, messages: int, tools: int) -> None:
        self.steps = step
        logger.info("%s step=%s messages=%s tools=%s", self.prefix, step, messages, tools)

    def reply(self, reply) -> None:
        log_reply(reply, f"{self.prefix} step#{self.steps}")

    def note(self, name: str, attributes: dict | None = None) -> None:
        telemetry.event(name, attributes)
