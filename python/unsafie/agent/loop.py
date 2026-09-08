import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from unsafie.agent import blocks, client, credentials, pricing, queue, request
from unsafie.agent.client import ApiError
from unsafie.agent.parser import MarkdownCodeParser
from unsafie.agent.session import Ctx
from unsafie.agent.trace import Recorder
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)


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


class Watcher:
    def __init__(self, runner: blocks.Runner, recorder: Recorder) -> None:
        self.runner = runner
        self.recorder = recorder
        self.parser = MarkdownCodeParser(self._on_block)

    def _on_block(self, code: str) -> None:
        self.runner.start(code)

    def __call__(self, name: str, data: dict) -> None:
        self.recorder.raw(name, data)
        if name == "text_delta":
            text = data.get("text") or ""
            self.parser.feed(text)

    def finish(self) -> None:
        self.parser.close()


async def run(
    ctx: Ctx,
    *,
    messages: list[dict],
    access_token: str,
    model: str,
    prompt: str,
    effort: str | None,
    budget_usd: float,
    recorder: Recorder,
    on_cost: Callable[[float], Awaitable[int]] | None = None,
) -> Result:
    result = Result()

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

        body = request.build(
            model=model,
            prompt=prompt,
            messages=messages,
            effort=effort,
            max_tokens=settings.gemini_max_output_tokens,
        )
        result.steps += 1
        recorder.request(result.steps, len(messages), 0)
        runner = blocks.Runner(ctx, recorder)
        watcher = Watcher(runner, recorder)
        try:
            reply = await client.send(access_token, model, body, on_event=watcher)
        except ApiError as e:
            watcher.finish()
            await runner.settle()
            result.status = "failed"
            result.failure = credentials.classify_api(e.status, e.kind, e.message)
            result.error = e.describe()
            recorder.failed(short(result.error, 600), e.kind)
            logger.warning("%s step=%s %s", ctx.prefix, result.steps, short(result.error, 600))
            return result

        watcher.finish()

        step_cost = pricing.cost(model, reply.usage)
        result.cost_usd += step_cost
        if on_cost is not None:
            await on_cost(step_cost)
        pricing.merge(result.usage, reply.usage)
        result.stop_reason = reply.stop_reason
        recorder.reply(reply)

        if reply.text:
            result.text = reply.text
            messages.append(reply.as_message())

        content = await runner.settle()
        result.ran += runner.count
        if runner.replied:
            result.replied = True

        extra = await queue.drain(ctx.turn_id)

        if runner.stopped:
            if extra is not None:
                recorder.note("unsafie.stop_blocked", {"reason": "pending messages"})
                logger.info(
                    "%s turn stopped via stop(), but injecting pending messages into next step",
                    ctx.prefix,
                )
                if content:
                    content.append({"type": "text", "text": extra})
                    messages.append({"role": "user", "content": content})
                else:
                    _ask(messages, extra)
                continue
            result.replied = True
            recorder.note("unsafie.turn_stopped")
            logger.info("%s turn stopped via stop()", ctx.prefix)
            return result

        if content:
            if extra is not None:
                recorder.note("unsafie.messages_injected")
                logger.info("%s injecting messages that arrived mid-turn", ctx.prefix)
                content.append({"type": "text", "text": extra})
            messages.append({"role": "user", "content": content})
            continue

        if extra is not None:
            recorder.note("unsafie.stop_blocked", {"reason": "pending messages"})
            _ask(messages, extra)
            continue

        return result

    logger.warning("%s hit the %s step ceiling", ctx.prefix, settings.agent_max_steps)
    return result
