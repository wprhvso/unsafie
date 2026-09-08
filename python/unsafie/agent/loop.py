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

MAX_REMINDERS = 2
NOTHING_SAID = (
    "Nothing of that reached the user: plain text is not delivered and no block called say(). "
    "Write a ```python block that calls say(...) — or page(...) plus say(link) when it is long."
)


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


def _watcher(runner: blocks.Runner, reader: blocks.Reader, recorder: Recorder):
    """Feeds the streamed text into the fence reader and fires every block as it closes."""

    def on_event(name: str, data: dict) -> None:
        recorder.raw(name, data)
        kind = name or str(data.get("type") or "")
        if kind != "content_block_delta":
            return
        delta = data.get("delta") or {}
        if delta.get("type") != "text_delta":
            return
        for code in reader.feed(str(delta.get("text") or "")):
            runner.start(code)

    return on_event


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
    reminders = 0

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
            definitions=request.tools([]),
            effort=effort,
            max_tokens=settings.claude_max_tokens,
        )
        result.steps += 1
        recorder.request(result.steps, len(messages), 0)
        runner = blocks.Runner(ctx, recorder)
        reader = blocks.Reader()
        try:
            reply = await client.send(credential, body, on_event=_watcher(runner, reader, recorder))
        except ApiError as e:
            for code in reader.flush():
                runner.start(code)
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

        for code in reader.flush():
            runner.start(code)

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

        if not result.replied and reminders < MAX_REMINDERS:
            reminders += 1
            recorder.note("unsafie.silent_turn", {"attempt": reminders})
            logger.info("%s said nothing to the user: %s", ctx.prefix, short(text))
            _ask(messages, NOTHING_SAID)
            continue

        return result

    logger.warning("%s hit the %s step ceiling", ctx.prefix, settings.agent_max_steps)
    if result.replied:
        return result
    result.status = "failed"
    result.error = f"stopped after {settings.agent_max_steps} steps without a reply"
    return result
