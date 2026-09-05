import logging
from uuid import UUID

from claude_agent_sdk import HookMatcher

from unsafie.agent import queue
from unsafie.agent.trace import Recorder
from unsafie.agent.tools.registry import reply_tools
from unsafie.log import short

logger = logging.getLogger(__name__)

NO_REPLY_REASON = "The user has not received a reply. Call send_message."


def build_hooks(prefix: str, turn_id: UUID, recorder: Recorder | None = None) -> dict:
    called: set[str] = set()
    replying = reply_tools()

    async def pre_tool(input_data, tool_use_id, context):
        name = input_data.get("tool_name")
        logger.info(
            "%s hook PreToolUse tool=%s input=%s",
            prefix,
            name,
            short(input_data.get("tool_input")),
        )
        # The only place where the start of a built-in tool is visible from this process.
        if recorder is not None:
            recorder.tool_started(name, input_data.get("tool_input"), tool_use_id)
        return {}

    async def track(input_data, tool_use_id, context):
        called.add(input_data.get("tool_name"))
        return {}

    async def post_tool(input_data, tool_use_id, context):
        if recorder is not None:
            recorder.tool_finished(
                input_data.get("tool_name"), tool_use_id, input_data.get("tool_response")
            )
        extra = queue.drain(turn_id)
        if extra is None:
            return {}
        logger.info("%s hook PostToolUse injecting pending messages", prefix)
        if recorder is not None:
            recorder.note("unsafie.messages_injected")
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": extra}}

    async def force_reply(input_data, tool_use_id, context):
        active = input_data.get("stop_hook_active")
        replied = bool(called & replying)
        extra = queue.drain(turn_id)
        if extra is not None:
            logger.info("%s hook Stop blocked: pending messages injected", prefix)
            if recorder is not None:
                recorder.note("unsafie.stop_blocked", {"reason": "pending messages"})
            return {"decision": "block", "reason": extra}
        if active or replied:
            return {}
        logger.warning("%s hook Stop blocked: no reply sent yet", prefix)
        if recorder is not None:
            recorder.note("unsafie.stop_blocked", {"reason": "no reply"})
        return {"decision": "block", "reason": NO_REPLY_REASON}

    return {
        "PreToolUse": [HookMatcher(hooks=[pre_tool])],
        "PostToolUse": [
            HookMatcher(matcher="^(" + "|".join(sorted(replying)) + ")$", hooks=[track]),
            HookMatcher(hooks=[post_tool]),
        ],
        "Stop": [HookMatcher(hooks=[force_reply])],
    }
