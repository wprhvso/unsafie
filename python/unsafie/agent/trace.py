import logging

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from unsafie.log import short

logger = logging.getLogger(__name__)


def _log_blocks(tag: str, blocks, prefix: str) -> None:
    for i, block in enumerate(blocks):
        if isinstance(block, TextBlock):
            logger.info("%s %s block[%s] text: %s", prefix, tag, i, short(block.text))
        elif isinstance(block, ThinkingBlock):
            logger.debug("%s %s block[%s] thinking: %s", prefix, tag, i, short(block.thinking))
        elif isinstance(block, ToolUseBlock):
            logger.info(
                "%s %s block[%s] tool_use id=%s name=%s input=%s",
                prefix,
                tag,
                i,
                block.id,
                block.name,
                short(block.input),
            )
        elif isinstance(block, ToolResultBlock):
            logger.info(
                "%s %s block[%s] tool_result for=%s is_error=%s content=%s",
                prefix,
                tag,
                i,
                block.tool_use_id,
                block.is_error,
                short(block.content),
            )
        else:
            logger.debug(
                "%s %s block[%s] %s: %s", prefix, tag, i, type(block).__name__, short(block)
            )


def log_sdk_message(m, prefix: str) -> None:
    if isinstance(m, AssistantMessage):
        logger.info("%s assistant model=%s blocks=%s", prefix, m.model, len(m.content))
        _log_blocks("assistant", m.content, prefix)
    elif isinstance(m, UserMessage):
        if isinstance(m.content, str):
            logger.info("%s user text: %s", prefix, short(m.content))
        else:
            _log_blocks("user", m.content, prefix)
    elif isinstance(m, SystemMessage):
        logger.info("%s system subtype=%s data=%s", prefix, m.subtype, short(m.data))
    elif isinstance(m, ResultMessage):
        logger.info(
            "%s result subtype=%s is_error=%s turns=%s duration=%sms session=%s cost=%s",
            prefix,
            m.subtype,
            m.is_error,
            m.num_turns,
            m.duration_ms,
            m.session_id,
            m.total_cost_usd,
        )
    else:
        logger.debug("%s %s: %s", prefix, type(m).__name__, short(m))
