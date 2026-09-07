import asyncio
import logging
import time
from dataclasses import dataclass, field

from unsafie.agent import client, credentials, pricing, queue, request
from unsafie.agent.client import ApiError
from unsafie.agent.tools.base import ToolContext
from unsafie.agent.tools.registry import ToolSpec
from unsafie.agent.trace import Recorder
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)

NO_REPLY = "The user has not received a reply. Call send_message."
EMPTY_RESULT = [{"type": "text", "text": "(no output)"}]


@dataclass
class Result:
    status: str = "ok"
    steps: int = 0
    cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)
    text: str | None = None
    error: str | None = None
    failure: credentials.Failure | None = None
    replied: bool = False
    stop_reason: str | None = None


def _image(block: dict) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": block.get("mimeType") or "image/png",
            "data": block.get("data") or "",
        },
    }


def _content(payload: dict) -> list[dict]:
    out: list[dict] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image" and "source" not in block:
            out.append(_image(block))
        else:
            out.append(block)
    return out or list(EMPTY_RESULT)


def _failed(call_id: str, message: str) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": [{"type": "text", "text": message}],
        "is_error": True,
    }


async def _invoke(
    ctx: ToolContext, tools: dict[str, ToolSpec], name: str, call_id: str, args: dict
) -> dict:
    spec = tools.get(name)
    if spec is None:
        logger.warning("%s tool=%s does not exist", ctx.prefix, name)
        return _failed(call_id, f"there is no tool named {name}")
    missing = [key for key in spec.required if key not in args]
    if missing:
        logger.warning("%s tool=%s missing %s", ctx.prefix, name, missing)
        return _failed(call_id, f"{name}: missing required argument(s): {', '.join(missing)}")
    try:
        payload = await asyncio.wait_for(
            spec.handler(ctx, args), timeout=settings.agent_tool_timeout
        )
    except TimeoutError:
        logger.warning("%s tool=%s timed out", ctx.prefix, name)
        return _failed(call_id, f"{name} timed out after {settings.agent_tool_timeout:.0f}s")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("%s tool=%s crashed", ctx.prefix, name)
        return _failed(call_id, f"{name} crashed: {type(e).__name__}: {e}")
    if not isinstance(payload, dict):
        return _failed(call_id, f"{name} returned {type(payload).__name__} instead of a result")
    result = {"type": "tool_result", "tool_use_id": call_id, "content": _content(payload)}
    if payload.get("is_error"):
        result["is_error"] = True
    return result


async def _call(
    ctx: ToolContext, tools: dict[str, ToolSpec], block: dict, recorder: Recorder
) -> dict:
    name = block.get("name") or ""
    call_id = block.get("id") or ""
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    recorder.tool_started(call_id, name, args)
    started = time.perf_counter()
    result = await _invoke(ctx, tools, name, call_id, args)
    recorder.tool_finished(call_id, name, result, (time.perf_counter() - started) * 1000)
    return result


async def run(
    ctx: ToolContext,
    *,
    messages: list[dict],
    credential,
    model: str,
    prompt: str,
    effort: str | None,
    budget_usd: float,
    definitions: list[dict],
    tools: dict[str, ToolSpec],
    recorder: Recorder,
) -> Result:
    result = Result()
    replying = {name for name, spec in tools.items() if spec.replies}
    catalogue = request.tools(definitions)
    marked = -1
    nudges = 0

    while result.steps < settings.agent_max_steps:
        if result.cost_usd >= budget_usd:
            logger.warning(
                "%s spent %.6f of %.6f after %s step(s)",
                ctx.prefix,
                result.cost_usd,
                budget_usd,
                result.steps,
            )
            result.status = "ok" if result.replied else "budget"
            return result

        marks = request.anchors(messages, marked)
        marked = len(messages) - 1
        body = request.build(
            model=model,
            prompt=prompt,
            messages=messages,
            marks=marks,
            definitions=catalogue,
            effort=effort,
            max_tokens=settings.claude_max_tokens,
        )
        result.steps += 1
        recorder.request(result.steps, len(messages), len(catalogue))
        try:
            reply = await client.send(credential, body, on_event=recorder.raw)
        except ApiError as e:
            if request.downgrade(model, e):
                result.steps -= 1
                recorder.note("unsafie.downgraded", {"reason": short(e.message, 200)})
                continue
            result.status = "failed"
            result.failure = credentials.classify_api(e.status, e.kind, e.message)
            result.error = e.describe()
            recorder.failed(short(result.error, 600), e.kind)
            logger.warning("%s step=%s %s", ctx.prefix, result.steps, short(result.error, 600))
            return result

        result.cost_usd += pricing.cost(reply.model or model, reply.usage)
        pricing.merge(result.usage, reply.usage)
        result.stop_reason = reply.stop_reason
        recorder.reply(reply)
        messages.append(reply.as_message())
        text = reply.text.strip()
        if text:
            result.text = text

        calls = reply.calls
        if calls:
            content: list[dict] = []
            for call in calls:
                content.append(await _call(ctx, tools, call, recorder))
                if call.get("name") in replying:
                    result.replied = True
            extra = await queue.drain(ctx.turn_id)
            if extra is not None:
                recorder.note("unsafie.messages_injected")
                logger.info("%s injecting messages that arrived mid-turn", ctx.prefix)
                content.append({"type": "text", "text": extra})
            messages.append({"role": "user", "content": content})
            continue

        if reply.stop_reason == "pause_turn":
            continue

        extra = await queue.drain(ctx.turn_id)
        if extra is not None:
            recorder.note("unsafie.stop_blocked", {"reason": "pending messages"})
            messages.append({"role": "user", "content": [{"type": "text", "text": extra}]})
            continue

        if not result.replied and nudges < settings.agent_max_nudges:
            nudges += 1
            recorder.note("unsafie.stop_blocked", {"reason": "no reply"})
            logger.warning("%s finished without a reply, nudging", ctx.prefix)
            messages.append({"role": "user", "content": [{"type": "text", "text": NO_REPLY}]})
            continue

        return result

    logger.warning("%s hit the %s step ceiling", ctx.prefix, settings.agent_max_steps)
    if result.replied:
        return result
    result.status = "failed"
    result.error = f"stopped after {settings.agent_max_steps} steps without a reply"
    return result
