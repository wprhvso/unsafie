import json
import logging
from dataclasses import dataclass, field

from unsafie.agent import blocks, client, credentials, pricing, queue, request
from unsafie.agent.client import ApiError
from unsafie.agent.parser import extract_code
from unsafie.agent.session import Ctx
from unsafie.agent.trace import Recorder
from unsafie.log import short
from unsafie.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Result:
    status: str = "ok"
    steps: int = 0
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


async def run(
    ctx: Ctx,
    *,
    messages: list[dict],
    access_token: str,
    model: str,
    prompt: str,
    effort: str | None,
    recorder: Recorder,
) -> Result:
    result = Result()

    while result.steps < settings.agent_max_steps:
        body = request.build(
            model=model,
            prompt=prompt,
            messages=messages,
            effort=effort,
            max_tokens=settings.gemini_max_output_tokens,
        )
        result.steps += 1
        recorder.request(result.steps, len(messages), 0)
        try:
            reply = await client.send(access_token, model, body, on_event=recorder.raw)
        except ApiError as e:
            failure = credentials.classify_api(e.status, e.kind, e.message)
            if credentials.blames_credential(failure):
                result.status = "failed"
                result.failure = failure
                result.error = e.describe()
                recorder.failed(short(result.error, 600), e.kind)
                logger.warning("%s step=%s %s", ctx.prefix, result.steps, short(result.error, 600))
                return result

            recorder.failed(short(e.describe(), 600), e.kind)
            logger.warning(
                "%s step=%s API error: %s, returning error in user block",
                ctx.prefix,
                result.steps,
                e.describe(),
            )
            _ask(
                messages,
                f"Error from model API: {e.describe()}. Please provide an executable bash block.",
            )
            continue

        pricing.merge(result.usage, reply.usage)
        result.stop_reason = reply.stop_reason
        recorder.reply(reply)

        if reply.text:
            result.text = reply.text
        messages.append(reply.as_message())

        if reply.stop_reason and reply.stop_reason not in ("STOP", "MAX_TOKENS"):
            recorder.note("unsafie.generation_stopped", {"reason": reply.stop_reason})
            logger.warning("%s step=%s stop_reason=%s", ctx.prefix, result.steps, reply.stop_reason)
            _ask(
                messages,
                f"Error: Generation stopped ({reply.stop_reason}). Please provide an executable bash block.",
            )
            continue

        code = extract_code(reply.text)
        if not code:
            recorder.note("unsafie.no_code_block")
            logger.warning(
                "%s step=%s model returned zero executable blocks", ctx.prefix, result.steps
            )
            if messages and messages[-1].get("role") == "assistant" and not (reply.text or "").strip():
                messages.pop()
            _ask(
                messages,
                "Error: No executable bash block found. Please provide an executable bash code block enclosed in ```bash ... ```.",
            )
            continue

        runner = blocks.Runner(ctx, recorder)
        await runner.run(code)
        result.ran += runner.count
        if runner.replied:
            result.replied = True

        extra, injected_raw = await queue.drain(ctx.turn_id)

        if runner.stopped:
            if extra is not None:
                injected_data = []
                for raw in injected_raw:
                    try:
                        injected_data.append(json.loads(raw))
                    except Exception:
                        injected_data.append(raw)
                payload = (
                    injected_data[0]
                    if len(injected_data) == 1 and isinstance(injected_data[0], dict)
                    else {"messages": injected_data}
                )
                recorder.note(
                    "unsafie.stop_blocked", {"reason": "pending messages", "injected": payload}
                )
                logger.info(
                    "%s turn stopped via stop(), but injecting pending messages into next step",
                    ctx.prefix,
                )
                content = runner.content()
                content.append({"type": "text", "text": extra})
                messages.append({"role": "user", "content": content})
                continue
            result.replied = True
            logger.info("%s turn stopped via stop()", ctx.prefix)
            return result

        content = runner.content()
        if extra is not None:
            injected_data = []
            for raw in injected_raw:
                try:
                    injected_data.append(json.loads(raw))
                except Exception:
                    injected_data.append(raw)
            payload = (
                injected_data[0]
                if len(injected_data) == 1 and isinstance(injected_data[0], dict)
                else {"messages": injected_data}
            )
            recorder.note("unsafie.messages_injected", payload)
            logger.info("%s injecting messages that arrived mid-turn", ctx.prefix)
            content.append({"type": "text", "text": extra})
        messages.append({"role": "user", "content": content})
        continue

    logger.warning("%s hit the %s step ceiling", ctx.prefix, settings.agent_max_steps)
    return result
