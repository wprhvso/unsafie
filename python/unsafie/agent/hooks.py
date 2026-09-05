import logging
from uuid import UUID

from claude_agent_sdk import HookMatcher

from unsafie.agent import queue
from unsafie.agent.tools.registry import reply_tools
from unsafie.log import short

logger = logging.getLogger(__name__)

NO_REPLY_REASON = "The user has not received a reply. Call send_message."


def build_hooks(prefix: str, turn_id: UUID) -> dict:
    called: set[str] = set()
    replying = reply_tools()

    async def pre_tool(input_data, tool_use_id, context):
        logger.info(
            "%s hook PreToolUse tool=%s input=%s",
            prefix,
            input_data.get("tool_name"),
            short(input_data.get("tool_input")),
        )
        return {}

    async def track(input_data, tool_use_id, context):
        called.add(input_data.get("tool_name"))
        return {}

    async def inject(input_data, tool_use_id, context):
        extra = queue.drain(turn_id)
        if extra is None:
            return {}
        logger.info("%s hook PostToolUse injecting pending messages", prefix)
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": extra}}

    async def force_reply(input_data, tool_use_id, context):
        active = input_data.get("stop_hook_active")
        replied = bool(called & replying)
        extra = queue.drain(turn_id)
        if extra is not None:
            logger.info("%s hook Stop blocked: pending messages injected", prefix)
            return {"decision": "block", "reason": extra}
        if active or replied:
            return {}
        logger.warning("%s hook Stop blocked: no reply sent yet", prefix)
        return {"decision": "block", "reason": NO_REPLY_REASON}

    return {
        "PreToolUse": [HookMatcher(hooks=[pre_tool])],
        "PostToolUse": [
            HookMatcher(matcher="^(" + "|".join(sorted(replying)) + ")$", hooks=[track]),
            HookMatcher(hooks=[inject]),
        ],
        "Stop": [HookMatcher(hooks=[force_reply])],
    }
