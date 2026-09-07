import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from unsafie import events, telemetry
from unsafie.agent import billing, credentials, live, loop, queue, request, segments, turns
from unsafie.agent.prompt import SYSTEM_PROMPT
from unsafie.agent.prompt.context import build_context
from unsafie.agent.request import DEFAULT_EFFORT
from unsafie.agent.tools import ToolContext, build_tools, enabled
from unsafie.agent.trace import Recorder
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.models.turn import Turn, TurnStatus
from unsafie.database.repositories.config import ConfigRepository
from unsafie.database.repositories.credential import CredentialRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.log import short
from unsafie.settings import settings
from unsafie.telegram import render, sender
from unsafie.telegram.chat_action import typing
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6

LOST_CONTEXT = (
    "The earlier part of this conversation could not be restored, so you are seeing it for the "
    "first time. The message below may reply to something you cannot see: say so plainly instead "
    "of guessing what it was about."
)


@dataclass
class Outcome:
    status: str
    next_at: datetime | None = None
    error: str | None = None
    cost_usd: float = 0.0


def prompt_for(message: Message, in_context: bool) -> str:
    data = render.describe(message)
    if "reply_to" in data:
        data["reply_to"]["in_context"] = in_context
    return json.dumps(data, ensure_ascii=False)


def _usage(span, result: loop.Result) -> None:
    telemetry.set_attrs(
        span,
        {
            attrs.GEN_AI_INPUT_TOKENS: result.usage.get("input_tokens"),
            attrs.GEN_AI_OUTPUT_TOKENS: result.usage.get("output_tokens"),
            "gen_ai.usage.cache_read_input_tokens": result.usage.get("cache_read_input_tokens"),
            "gen_ai.usage.cache_creation_input_tokens": result.usage.get(
                "cache_creation_input_tokens"
            ),
        },
    )


class Meter:
    def __init__(self, held: billing.Hold, turn_id: UUID) -> None:
        self.held = held
        self.turn_id = turn_id
        self.ratio = 1.0
        self.base = 0
        self.charged = 0
        self.cost = 0.0
        self.segment = 0.0

    def begin(self, ratio: float) -> None:
        self.base = self.charged
        self.segment = 0.0
        self.ratio = ratio

    async def take(self, cost_usd: float) -> int:
        self.cost += cost_usd
        self.segment += cost_usd
        target = self.base + billing.charge_units(self.segment, self.ratio)
        delta = target - self.charged
        if delta <= 0:
            return 0
        self.charged = target
        balance = await self.held.spend(delta)
        live.emit(
            self.turn_id,
            "charge",
            units=delta,
            total=self.charged,
            balance=balance,
            cost_usd=self.cost,
        )
        return delta


async def _bill(ctx: ToolContext, credential, result: loop.Result, meter: Meter) -> int:
    leftover = result.cost_usd - meter.segment
    if leftover > 0:
        await meter.take(leftover)
    charge = meter.charged - meter.base
    if charge:
        logger.info("%s charged %s for this attempt", ctx.prefix, charge)
    async with SessionLocal() as session:
        await TurnRepository(session).record(
            ctx.turn_id,
            credential_id=credential.id,
            cost_usd=result.cost_usd,
            charge=charge,
            num_turns=result.steps,
            result=result.text,
        )
    return charge


async def _punish(credential, result: loop.Result) -> None:
    async with SessionLocal() as session:
        creds = CredentialRepository(session)
        row = await creds.get(credential.id)
        if row is None:
            return
        cooldown = credentials.cooldown_for(row.kind, row.failures + 1, result.failure)
        disable = result.failure == credentials.Failure.AUTH
        await creds.failed(
            credential.id, error=result.error or "", cooldown_until=cooldown, disable=disable
        )
    events.publish(
        "credential.failed",
        credential_id=credential.id,
        kind=str(credential.kind),
        failure=str(result.failure),
        cooldown_until=cooldown.isoformat() if cooldown else None,
        disabled=disable,
    )


async def _execute(
    ctx: ToolContext,
    messages: list[dict],
    servers: list[str],
    system_prompt: str,
    held: billing.Hold,
) -> Outcome:
    prefix = ctx.prefix
    tried: set[int] = set()
    spent = 0.0
    meter = Meter(held, ctx.turn_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        with telemetry.span(
            "agent.attempt",
            attributes={attrs.ATTEMPT: attempt, attrs.TURN_ID: str(ctx.turn_id)},
        ) as attempt_span:
            async with SessionLocal() as session:
                creds = CredentialRepository(session)
                credential = await creds.pick(tried)
                if credential is None:
                    next_at = await creds.next_cooldown()
                    telemetry.refused(attempt_span, f"no usable credential (tried={sorted(tried)})")
                    logger.warning("%s no usable credential (tried=%s)", prefix, sorted(tried))
                    return Outcome("no_credentials", next_at=next_at, cost_usd=spent)
                config = await ConfigRepository(session).get()
                ratio = billing.ratio_for(config, credential.kind)
                user = await UserRepository(session).get_or_create(ctx.user_id)
                model = user.model or settings.claude_model
                effort = user.effort or DEFAULT_EFFORT

            meter.begin(ratio)
            left = held.usd(ratio)
            if left <= 0:
                empty = "busy" if held.balance > 0 else "empty_balance"
                telemetry.refused(attempt_span, empty)
                logger.warning("%s stopped: nothing left to spend (%s)", prefix, empty)
                return Outcome("ok" if spent else empty, cost_usd=spent)

            definitions, tools = build_tools(ctx, servers)
            applied = request.applied_thinking(model) or {}
            telemetry.set_attrs(
                attempt_span,
                {
                    attrs.CREDENTIAL_ID: credential.id,
                    attrs.CREDENTIAL_KIND: str(credential.kind),
                    attrs.GEN_AI_MODEL: model,
                    attrs.EFFORT: effort,
                    attrs.THINKING: applied.get("type", "off"),
                    attrs.THINKING_DISPLAY: applied.get("display", "off"),
                    attrs.BUDGET_USD: left,
                    attrs.SERVERS: servers or None,
                },
            )
            logger.info(
                "%s attempt=%s credential=%s(%s) model=%s effort=%s thinking=%s/%s ratio=%s "
                "budget=%.6f messages=%s tools=%s servers=%s",
                prefix,
                attempt,
                credential.id,
                credential.kind,
                model,
                effort,
                applied.get("type", "off"),
                applied.get("display", "off"),
                ratio,
                left,
                len(messages),
                len(definitions),
                servers,
            )

            live.emit(
                ctx.turn_id,
                "attempt.start",
                attempt=attempt,
                model=model,
                effort=effort,
                budget_usd=left,
                ratio=ratio,
                budget_units=held.units,
                balance_units=held.balance,
                tools=len(definitions),
                servers=servers,
                thinking=applied.get("type", "off"),
                display=applied.get("display", "off"),
                configured=settings.claude_thinking_display or "off",
            )
            started = time.perf_counter()
            with telemetry.span(
                "gen_ai.invoke_agent",
                kind=telemetry.CLIENT,
                attributes={
                    attrs.GEN_AI_SYSTEM: "anthropic",
                    attrs.GEN_AI_OPERATION: "invoke_agent",
                    attrs.GEN_AI_MODEL: model,
                    attrs.EFFORT: effort,
                    attrs.BUDGET_USD: left,
                    attrs.TURN_ID: str(ctx.turn_id),
                },
            ) as query_span:
                result = await loop.run(
                    ctx,
                    messages=messages,
                    credential=credential,
                    model=model,
                    prompt=system_prompt,
                    effort=effort,
                    budget_usd=left,
                    definitions=definitions,
                    tools=tools,
                    recorder=Recorder(prefix, live.of(ctx.turn_id)),
                    on_cost=meter.take,
                )
                elapsed = (time.perf_counter() - started) * 1000
                spent += result.cost_usd
                _usage(query_span, result)
                telemetry.set_attrs(
                    query_span,
                    {
                        attrs.SDK_MESSAGES: len(messages),
                        attrs.NUM_TURNS: result.steps,
                        attrs.COST_USD: result.cost_usd,
                        attrs.GEN_AI_FINISH_REASONS: [result.stop_reason]
                        if result.stop_reason
                        else None,
                        attrs.COMPLETION: telemetry.content(result.text),
                    },
                )
                if result.status != "ok":
                    telemetry.fail(
                        query_span, RuntimeError(short(result.error or result.status, 300))
                    )

            charge = await _bill(ctx, credential, result, meter)
            telemetry.set_attrs(
                attempt_span,
                {
                    attrs.OUTCOME: result.status,
                    attrs.COST_USD: result.cost_usd,
                    attrs.CHARGE: charge,
                    attrs.NUM_TURNS: result.steps,
                    attrs.FAILURE: str(result.failure) if result.failure else None,
                },
            )
            logger.info(
                "%s attempt=%s %s steps=%s cost=%.6f charge=%s in %.1fms",
                prefix,
                attempt,
                result.status,
                result.steps,
                result.cost_usd,
                charge,
                elapsed,
            )

            live.emit(
                ctx.turn_id,
                "attempt.end",
                attempt=attempt,
                status=result.status,
                steps=result.steps,
                cost_usd=result.cost_usd,
                charge=charge,
                total_cost=meter.cost,
                total_charge=meter.charged,
                usage=result.usage,
                stop_reason=result.stop_reason,
                error=short(result.error, 300) if result.error else None,
            )

            if result.status == "ok":
                async with SessionLocal() as session:
                    await CredentialRepository(session).succeeded(credential.id, result.cost_usd)
                return Outcome("ok", cost_usd=spent)
            if result.status == "budget":
                return Outcome("empty_balance", cost_usd=spent)
            if result.failure is not None and credentials.blames_credential(result.failure):
                logger.warning(
                    "%s credential=%s failed (%s): %s",
                    prefix,
                    credential.id,
                    result.failure,
                    short(result.error, 600),
                )
                tried.add(credential.id)
                await _punish(credential, result)
                continue
            return Outcome("failed", error=result.error, cost_usd=spent)
    return Outcome("failed", error="attempts exhausted", cost_usd=spent)


async def notify(bot: Bot, turn: Turn, text: str) -> None:
    try:
        await sender.send(
            bot,
            bot_id=turn.bot_id,
            chat_id=turn.chat_id,
            markdown=text,
            kind=ResponseKind.SYSTEM,
            turn=turn,
        )
    except TelegramAPIError as e:
        logger.error(
            "bot=%s chat=%s turn=%s notify failed error=%s", turn.bot_id, turn.chat_id, turn.id, e
        )


def _failure_text(locale: str, outcome: Outcome) -> str:
    if outcome.status == "empty_balance":
        return t("agent-empty-balance", locale)
    if outcome.status == "busy":
        return t("agent-budget-busy", locale)
    if outcome.status == "no_credentials":
        when = ""
        if outcome.next_at is not None:
            minutes = max(1, int((outcome.next_at - datetime.now(UTC)).total_seconds() // 60) + 1)
            when = t("agent-no-credentials-when", locale, minutes=minutes)
        return t("agent-no-credentials", locale, when=when)
    return t("agent-failure", locale)


async def run_turn(bot: Bot, plan: turns.Plan, prompt: str, locale: str) -> None:
    turn = plan.turn
    ctx = ToolContext(bot, turn.bot_id, turn.chat_id, turn.user_id, turn.id, locale)
    prefix = ctx.prefix
    history = await segments.load(turn)
    system_prompt = history.system or SYSTEM_PROMPT
    snapshot = None if history.system else system_prompt
    messages = history.messages
    if history.lost:
        logger.warning("%s has a parent but no stored history, starting over", prefix)
        prompt = LOST_CONTEXT + "\n\n" + prompt
    status = TurnStatus.FAILED
    note: str | None = None
    stream = await live.begin(turn)
    if stream is not None:
        stream.emit(
            "turn.start",
            turn_id=str(turn.id),
            root_id=str(turn.root_id),
            chat_id=turn.chat_id,
            resumed=len(messages),
            prompt=live.clip(prompt)[0],
        )
    events.publish(
        "turn.started",
        turn_id=str(turn.id),
        root_id=str(turn.root_id),
        bot_id=turn.bot_id,
        chat_id=turn.chat_id,
        user_id=turn.user_id,
        resumed=len(messages),
    )
    with telemetry.span(
        "agent.turn",
        attributes={
            attrs.TURN_ID: str(turn.id),
            attrs.ROOT_ID: str(turn.root_id),
            attrs.BOT_ID: turn.bot_id,
            attrs.CHAT_ID: turn.chat_id,
            attrs.USER_ID: turn.user_id,
            attrs.LOCALE: locale,
            attrs.GEN_AI_CONVERSATION: str(turn.root_id),
        },
    ) as turn_span:
        base = len(messages)
        try:
            async with turns.alive(turn.id), typing(bot, turn.chat_id, prefix):
                with telemetry.span("agent.context"):
                    async with SessionLocal() as session:
                        servers = await enabled(session, ctx)
                        context = await build_context(session, ctx, servers)
                messages.append(request.user(prompt, context))
                async with billing.hold(turn.user_id, turn.id) as held:
                    telemetry.annotate(**{attrs.LOCKED: held.units})
                    while True:
                        outcome = await _execute(ctx, messages, servers, system_prompt, held)
                        if outcome.status != "ok":
                            await queue.clear(turn.id)
                            note = (
                                outcome.status
                                if outcome.error is None
                                else short(outcome.error, 1000)
                            )
                            logger.info("%s finished with %s", prefix, outcome.status)
                            await notify(bot, turn, _failure_text(locale, outcome))
                            return
                        leftover = await turns.finish_or_continue(
                            turn.id, turn.bot_id, turn.chat_id
                        )
                        if leftover is None:
                            status = TurnStatus.DONE
                            return
                        messages.append(request.user(leftover))
                        telemetry.event("unsafie.turn_rerun")
                        logger.info(
                            "%s re-running with messages that arrived after the reply", prefix
                        )
        except Exception as e:
            telemetry.fail(turn_span, e)
            logger.exception("%s turn crashed", prefix)
            await queue.clear(turn.id)
            note = "crashed"
            await notify(bot, turn, t("agent-failure", locale))
        finally:
            await turns.seal(turn.id)
            await segments.save(turn, messages[base:], snapshot)
            async with SessionLocal() as session:
                await TurnRepository(session).finish(turn.id, status, note)
                fresh = await TurnRepository(session).get(turn.id)
            telemetry.set_attrs(
                turn_span,
                {
                    attrs.TURN_STATUS: str(status),
                    attrs.COST_USD: fresh.cost_usd if fresh else None,
                    attrs.CHARGE: fresh.charge if fresh else None,
                    attrs.REFUSAL: note,
                },
            )
            events.publish(
                "turn.finished",
                turn_id=str(turn.id),
                root_id=str(turn.root_id),
                bot_id=turn.bot_id,
                chat_id=turn.chat_id,
                user_id=turn.user_id,
                status=str(status),
                cost_usd=fresh.cost_usd if fresh else None,
                charge=fresh.charge if fresh else 0,
                note=note,
            )
            live.emit(
                turn.id,
                "turn.end",
                status=str(status),
                steps=fresh.num_turns if fresh else 0,
                cost_usd=fresh.cost_usd if fresh else None,
                charge=fresh.charge if fresh else 0,
                note=note,
            )
            await live.end(turn.id)


async def dispatch(
    bot: Bot,
    *,
    bot_id: int,
    chat_id: int,
    user_id: int,
    reply_to: int | None,
    update_db_id: int | None,
    build_prompt: Callable[[bool], str],
    locale: str | None = None,
    what: str,
) -> None:
    with telemetry.span(
        "turn.route",
        attributes={
            attrs.BOT_ID: bot_id,
            attrs.CHAT_ID: chat_id,
            attrs.USER_ID: user_id,
            attrs.MESSAGE_ID: reply_to,
        },
    ) as span:
        plan = await turns.route(
            bot_id=bot_id,
            chat_id=chat_id,
            user_id=user_id,
            reply_to=reply_to,
            update_db_id=update_db_id,
        )
        telemetry.set_attrs(
            span,
            {
                attrs.TURN_ID: str(plan.turn.id),
                attrs.ROOT_ID: str(plan.turn.root_id),
                attrs.INJECTED: plan.inject,
            },
        )
    prompt = build_prompt(plan.in_context)
    logger.debug("bot=%s chat=%s %s prompt=%s", bot_id, chat_id, what, short(prompt))
    if plan.inject:
        n = await queue.enqueue(plan.turn.id, prompt)
        telemetry.annotate(**{attrs.INJECTED: True, attrs.TURN_ID: str(plan.turn.id)})
        logger.info(
            "bot=%s chat=%s %s queued into turn=%s (pending=%s)",
            bot_id,
            chat_id,
            what,
            plan.turn.id,
            n,
        )
        return
    if locale is None:
        async with SessionLocal() as session:
            user = await UserRepository(session).get(user_id)
        locale = user.locale if user and user.locale else settings.default_locale
    await run_turn(bot, plan, prompt, locale)


async def _user_locale(user_id: int, tg_user) -> str:
    from unsafie.telegram.handlers.locale import locale_for

    return await locale_for(user_id, tg_user)


async def handle(message: Message, bot_id: int, update_db_id: int | None) -> None:
    if message.from_user is None or message.bot is None:
        return
    if update_db_id is None:
        logger.error(
            "bot=%s chat=%s msg=%s update not persisted",
            bot_id,
            message.chat.id,
            message.message_id,
        )
        return
    await dispatch(
        message.bot,
        bot_id=bot_id,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        reply_to=message.reply_to_message.message_id if message.reply_to_message else None,
        update_db_id=update_db_id,
        build_prompt=lambda in_context: prompt_for(message, in_context),
        locale=await _user_locale(message.from_user.id, message.from_user),
        what=f"msg={message.message_id}",
    )


async def handle_callback(
    query: CallbackQuery, message: Message, bot_id: int, update_db_id: int | None
) -> None:
    if query.bot is None or update_db_id is None:
        return
    prompt = json.dumps(render.describe_callback(query), ensure_ascii=False)
    await dispatch(
        query.bot,
        bot_id=bot_id,
        chat_id=message.chat.id,
        user_id=query.from_user.id,
        reply_to=message.message_id,
        update_db_id=update_db_id,
        build_prompt=lambda _: prompt,
        locale=await _user_locale(query.from_user.id, query.from_user),
        what=f"callback={query.id}",
    )


async def run_scheduled(bot: Bot, task) -> None:
    prompt = json.dumps(render.describe_scheduled(task), ensure_ascii=False)
    await dispatch(
        bot,
        bot_id=task.bot_id,
        chat_id=task.chat_id,
        user_id=task.user_id,
        reply_to=task.origin_message_id,
        update_db_id=None,
        build_prompt=lambda _: prompt,
        what=f"task={task.id}",
    )


async def run_watch(bot: Bot, watch, host, output: str, exit_code: int) -> None:
    prompt = json.dumps(render.describe_watch(watch, host, output, exit_code), ensure_ascii=False)
    await dispatch(
        bot,
        bot_id=watch.bot_id,
        chat_id=watch.chat_id,
        user_id=watch.user_id,
        reply_to=watch.origin_message_id,
        update_db_id=None,
        build_prompt=lambda _: prompt,
        what=f"watch={watch.id}",
    )
