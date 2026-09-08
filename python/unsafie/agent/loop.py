import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from unsafie.agent import blocks, client, credentials, pricing, queue, request
from unsafie.agent.client import ApiError
from unsafie.agent.session import Ctx
from unsafie.agent.trace import Recorder
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)

TOOL = request.PYTHON_TOOL_NAME


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
    ran: int = 0


def _ask(messages: list[dict], value: str) -> None:
    block = {"type": "text", "text": value}
    last = messages[-1] if messages else None
    if last is not None and last.get("role") == "user" and isinstance(last.get("content"), list):
        last["content"].append(block)
        return
    messages.append({"role": "user", "content": [block]})


def _code(raw: str) -> str | None:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    code = parsed.get("code")
    return code if isinstance(code, str) else None


class Watcher:
    """Reads the raw stream and starts every python call the moment its arguments close."""

    def __init__(self, runner: blocks.Runner, recorder: Recorder) -> None:
        self.runner = runner
        self.recorder = recorder
        self.open: dict[int, dict] = {}

    def __call__(self, name: str, data: dict) -> None:
        self.recorder.raw(name, data)
        kind = name or str(data.get("type") or "")
        if kind == "content_block_start":
            block = data.get("content_block") or {}
            if block.get("type") == "tool_use" and block.get("name") == TOOL:
                self.open[int(data.get("index", 0))] = {"id": str(block.get("id") or ""), "args": ""}
            return
        if kind == "content_block_delta":
            delta = data.get("delta") or {}
            if delta.get("type") != "input_json_delta":
                return
            pending = self.open.get(int(data.get("index", 0)))
            if pending is not None:
                pending["args"] += str(delta.get("partial_json") or "")
            return
        if kind == "content_block_stop":
            pending = self.open.pop(int(data.get("index", 0)), None)
            if pending is None or not pending["id"]:
                return
            code = _code(pending["args"])
            if code is None:
                self.runner.refuse(
                    pending["id"],
                    "the arguments were not a JSON object with a string 'code' field",
                )
                return
            self.runner.start(pending["id"], code)


def _unanswered(reply, runner: blocks.Runner) -> None:
    """Every tool_use must come back with a tool_result, whatever the stream looked like."""
    for block in reply.calls:
        call_id = str(block.get("id") or "")
        if block.get("name") != TOOL or not call_id or runner.handled(call_id):
            continue
        code = (block.get("input") or {}).get("code")
        if isinstance(code, str):
            runner.start(call_id, code)
        else:
            runner.refuse(call_id, "no 'code' argument arrived")


async def run(
    ctx: Ctx,
    *,
    messages: list[dict],
    credential,
    model: str,
    prompt: str,
    effort: str | None,
    budget_usd: float,
    recorder: Recorder,
    on_cost: Callable[[float], Awaitable[int]] | None = None,
) -> Result:
    result = Result()
    marked = -1
    definitions = request.tools()

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
            definitions=definitions,
            effort=effort,
            max_tokens=settings.claude_max_tokens,
        )
        result.steps += 1
        recorder.request(result.steps, len(messages), len(definitions))
        runner = blocks.Runner(ctx, recorder)
        try:
            reply = await client.send(credential, body, on_event=Watcher(runner, recorder))
        except ApiError as e:
            await runner.settle()
            dropped = request.downgrade(model, e)
            if dropped:
                result.steps -= 1
                recorder.note(
                    "unsafie.downgraded", {"dropped": dropped, "reason": short(e.message, 200)}
                )
                continue
            result.status = "failed"
            result.failure = credentials.classify_api(e.status, e.kind, e.message)
            result.error = e.describe()
            recorder.failed(short(result.error, 600), e.kind)
            logger.warning("%s step=%s %s", ctx.prefix, result.steps, short(result.error, 600))
            return result

        _unanswered(reply, runner)

        step_cost = pricing.cost(reply.model or model, reply.usage)
        result.cost_usd += step_cost
        if on_cost is not None:
            await on_cost(step_cost)
        pricing.merge(result.usage, reply.usage)
        result.stop_reason = reply.stop_reason
        recorder.reply(reply)
        if reply.content:
            messages.append(reply.as_message())
        text = reply.text.strip()
        if text:
            result.text = text
            logger.info("%s wrote %s chars of text nobody will read", ctx.prefix, len(text))

        content = await runner.settle()
        result.ran += runner.count
        if runner.replied:
            result.replied = True
        if content:
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
            _ask(messages, extra)
            continue

        return result

    logger.warning("%s hit the %s step ceiling", ctx.prefix, settings.agent_max_steps)
    return result
