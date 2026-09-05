import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from claude_agent_sdk import (
    CLIConnectionError,
    CLIJSONDecodeError,
    ProcessError,
    ResultMessage,
    SystemMessage,
    query,
)

from unsafie import events, telemetry
from unsafie.agent import billing, credentials, queue, turns
from unsafie.agent.options import DEFAULT_EFFORT, build_options
from unsafie.agent.prompt.context import build_context
from unsafie.agent.tools import ToolContext, available_servers
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


@dataclass
class Outcome:
    status: str
    session_id: str | None = None
    next_at: datetime | None = None
    error: str | None = None


def prompt_for(message: Message, in_context: bool) -> str:
    data = render.describe(message)
    if "reply_to" in data:
        data["reply_to"]["in_context"] = in_context
    return json.dumps(data, ensure_ascii=False)


async def _execute(
    ctx: ToolContext,
    prompt: str,
    *,
    resume: str | None,
    fork: bool,
    session_id: str | None,
) -> Outcome:
    prefix = ctx.prefix
    tried: set[int] = set()
    fresh_session_retried = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        with telemetry.span(
            "agent.attempt",
            attributes={
                attrs.ATTEMPT: attempt,
                attrs.TURN_ID: str(ctx.turn_id),
                attrs.RESUME: resume,
                attrs.FORK: fork,
            },
        ) as attempt_span:
            async with SessionLocal() as session:
                creds = CredentialRepository(session)
                cred = await creds.pick(tried)
                if cred is None:
                    next_at = await creds.next_cooldown()
                    telemetry.refused(attempt_span, f"no usable credential (tried={sorted(tried)})")
                    logger.warning("%s no usable credential (tried=%s)", prefix, sorted(tried))
                    return Outcome("no_credentials", next_at=next_at)
                config = await ConfigRepository(session).get()
                ratio = billing.ratio_for(config, cred.kind)
                user = await UserRepository(session).get_or_create(ctx.user_id)
                budget = billing.budget_usd(user.balance, user.budget, ratio)
                model = user.model or settings.claude_model
                effort = user.effort or DEFAULT_EFFORT
                if budget <= 0:
                    telemetry.refused(attempt_span, "empty balance")
                    logger.warning("%s aborted: empty balance", prefix)
                    return Outcome("empty_balance")
                with telemetry.span("agent.context"):
                    servers = await available_servers(session, ctx)
                    context = await build_context(session, ctx, servers)
            telemetry.set_attrs(
                attempt_span,
                {
                    attrs.CREDENTIAL_ID: cred.id,
                    attrs.CREDENTIAL_KIND: str(cred.kind),
                    attrs.GEN_AI_MODEL: model,
                    attrs.EFFORT: effort,
                    attrs.BUDGET_USD: budget,
                    attrs.SERVERS: servers or None,
                },
            )
            logger.info(
                "%s attempt=%s credential=%s(%s) model=%s effort=%s ratio=%s budget=%.6f "
                "resume=%s fork=%s servers=%s",
                prefix,
                attempt,
                cred.id,
                cred.kind,
                model,
                effort,
                ratio,
                budget,
                resume,
                fork,
                servers,
            )
            stderr: list[str] = []
            result: ResultMessage | None = None
            seen_session: str | None = None
            error: str | None = None
            count = 0
            with telemetry.span(
                "gen_ai.invoke_agent",
                kind=telemetry.CLIENT,
                attributes={
                    attrs.GEN_AI_SYSTEM: "anthropic",
                    attrs.GEN_AI_OPERATION: "invoke_agent",
                    attrs.GEN_AI_MODEL: model,
                    attrs.GEN_AI_CONVERSATION: resume or session_id,
                    attrs.EFFORT: effort,
                    attrs.BUDGET_USD: budget,
                    attrs.TURN_ID: str(ctx.turn_id),
                    attrs.PROMPT: telemetry.content(prompt),
                },
            ) as query_span:
                recorder = Recorder(prefix, query_span)
                options = build_options(
                    ctx,
                    resume=resume,
                    fork=fork,
                    session_id=session_id,
                    model=model,
                    effort=effort,
                    budget_usd=budget,
                    context=context,
                    servers=servers,
                    env=credentials.env_for(cred),
                    stderr=stderr.append,
                    recorder=recorder,
                )
                # Tools are called from the SDK's own tasks: this is the context they attach to.
                ctx.trace.capture()
                started = time.perf_counter()
                try:
                    async for m in query(prompt=prompt, options=options):
                        count += 1
                        recorder.message(m)
                        if isinstance(m, SystemMessage) and m.subtype == "init":
                            seen_session = m.data.get("session_id") or seen_session
                        elif isinstance(m, ResultMessage):
                            result = m
                            seen_session = m.session_id or seen_session
                except (ProcessError, CLIConnectionError, CLIJSONDecodeError) as e:
                    error = f"{e}\n" + "\n".join(stderr[-30:])
                finally:
                    ctx.trace.release()
                    recorder.close()
                elapsed = (time.perf_counter() - started) * 1000
                if error is None and result is None:
                    error = "sdk finished without result\n" + "\n".join(stderr[-30:])
                if (
                    error is None
                    and result is not None
                    and (result.is_error or result.subtype != "success")
                ):
                    error = f"{result.subtype}: {result.result or ''}\n" + "\n".join(stderr[-30:])
                telemetry.set_attrs(
                    query_span,
                    {
                        attrs.SDK_MESSAGES: count,
                        attrs.GEN_AI_CONVERSATION: seen_session,
                        attrs.NUM_TURNS: result.num_turns if result else None,
                        attrs.COST_USD: result.total_cost_usd if result else None,
                        attrs.GEN_AI_FINISH_REASONS: [result.subtype] if result else None,
                        attrs.COMPLETION: telemetry.content(result.result) if result else None,
                    },
                )
                _usage(query_span, result)
                if error is not None:
                    telemetry.fail(query_span, RuntimeError(short(error, 300)))

            if error is None and result is not None:
                charge = billing.charge_units(result.total_cost_usd, ratio)
                async with SessionLocal() as session:
                    if charge:
                        updated = await UserRepository(session).charge(ctx.user_id, charge)
                        logger.info(
                            "%s charged %s, balance now %s", prefix, charge, updated.balance
                        )
                    await CredentialRepository(session).succeeded(cred.id, result.total_cost_usd)
                    await TurnRepository(session).record(
                        ctx.turn_id,
                        credential_id=cred.id,
                        cost_usd=result.total_cost_usd,
                        charge=charge,
                        num_turns=result.num_turns,
                        result=result.result,
                    )
                telemetry.set_attrs(
                    attempt_span,
                    {
                        attrs.OUTCOME: "ok",
                        attrs.COST_USD: result.total_cost_usd,
                        attrs.CHARGE: charge,
                        attrs.NUM_TURNS: result.num_turns,
                    },
                )
                logger.info(
                    "%s ok credential=%s turns=%s cost=%s charge=%s in %.1fms",
                    prefix,
                    cred.id,
                    result.num_turns,
                    result.total_cost_usd,
                    charge,
                    elapsed,
                )
                return Outcome("ok", session_id=seen_session or resume or session_id)

            failure = credentials.classify(error or "")
            telemetry.set_attrs(
                attempt_span, {attrs.OUTCOME: "failed", attrs.FAILURE: str(failure)}
            )
            logger.warning(
                "%s attempt=%s failed credential=%s failure=%s: %s",
                prefix,
                attempt,
                cred.id,
                failure,
                short(error, 600),
            )
            if (
                failure == credentials.Failure.MISSING_SESSION
                and resume
                and not fresh_session_retried
            ):
                fresh_session_retried = True
                resume, fork, session_id = None, False, str(uuid.uuid4())
                async with SessionLocal() as session:
                    await TurnRepository(session).set_session(ctx.turn_id, session_id)
                continue
            if credentials.blames_credential(failure):
                tried.add(cred.id)
                async with SessionLocal() as session:
                    creds = CredentialRepository(session)
                    row = await creds.get(cred.id)
                    if row is not None:
                        cooldown = credentials.cooldown_for(row.kind, row.failures + 1, failure)
                        await creds.failed(
                            cred.id,
                            error=error or "",
                            cooldown_until=cooldown,
                            disable=failure == credentials.Failure.AUTH,
                        )
                        events.publish(
                            "credential.failed",
                            credential_id=cred.id,
                            kind=str(row.kind),
                            failure=str(failure),
                            cooldown_until=cooldown.isoformat() if cooldown else None,
                            disabled=failure == credentials.Failure.AUTH,
                        )
                if seen_session:
                    resume, fork, session_id = seen_session, False, None
                continue
            return Outcome("failed", session_id=seen_session, error=error)
    return Outcome("failed", error="attempts exhausted")


def _usage(span, result: ResultMessage | None) -> None:
    """Token counts, when the SDK reports them."""
    usage = getattr(result, "usage", None)
    if not isinstance(usage, dict):
        return
    telemetry.set_attrs(
        span,
        {
            attrs.GEN_AI_INPUT_TOKENS: usage.get("input_tokens"),
            attrs.GEN_AI_OUTPUT_TOKENS: usage.get("output_tokens"),
            "gen_ai.usage.cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "gen_ai.usage.cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        },
    )


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
    resume, fork, session_id = plan.resume, plan.fork, plan.session_id
    status = TurnStatus.FAILED
    note: str | None = None
    events.publish(
        "turn.started",
        turn_id=str(turn.id),
        bot_id=turn.bot_id,
        chat_id=turn.chat_id,
        user_id=turn.user_id,
        resume=resume is not None,
        fork=fork,
    )
    with telemetry.span(
        "agent.turn",
        attributes={
            attrs.TURN_ID: str(turn.id),
            attrs.BOT_ID: turn.bot_id,
            attrs.CHAT_ID: turn.chat_id,
            attrs.USER_ID: turn.user_id,
            attrs.LOCALE: locale,
            attrs.RESUME: resume,
            attrs.FORK: fork,
            attrs.GEN_AI_CONVERSATION: session_id or resume,
        },
    ) as turn_span:
        try:
            async with typing(bot, turn.chat_id, prefix):
                while True:
                    outcome = await _execute(
                        ctx, prompt, resume=resume, fork=fork, session_id=session_id
                    )
                    if outcome.session_id and outcome.session_id != turn.session_id:
                        async with SessionLocal() as session:
                            await TurnRepository(session).set_session(turn.id, outcome.session_id)
                        turn.session_id = outcome.session_id
                    if outcome.status != "ok":
                        queue.clear(turn.id)
                        note = (
                            outcome.status
                            if outcome.error is None
                            else short(outcome.error, 1000)
                        )
                        logger.info("%s finished with %s", prefix, outcome.status)
                        await notify(bot, turn, _failure_text(locale, outcome))
                        return
                    resume, fork, session_id = outcome.session_id, False, None
                    leftover = await turns.finish_or_continue(
                        turn.id, turn.bot_id, turn.chat_id, queue.drain
                    )
                    if leftover is None:
                        status = TurnStatus.DONE
                        return
                    prompt = leftover
                    telemetry.event("unsafie.turn_rerun")
                    logger.info("%s re-running with messages that arrived after Stop", prefix)
        except Exception as e:
            telemetry.fail(turn_span, e)
            logger.exception("%s turn crashed", prefix)
            queue.clear(turn.id)
            note = "crashed"
            await notify(bot, turn, t("agent-failure", locale))
        finally:
            turns.abandon(turn.id)
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
                bot_id=turn.bot_id,
                chat_id=turn.chat_id,
                user_id=turn.user_id,
                status=str(status),
                cost_usd=fresh.cost_usd if fresh else None,
                charge=fresh.charge if fresh else 0,
                note=note,
            )


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
                attrs.INJECTED: plan.inject,
                attrs.RESUME: plan.resume,
                attrs.FORK: plan.fork,
            },
        )
    prompt = build_prompt(plan.in_context)
    logger.debug("bot=%s chat=%s %s prompt=%s", bot_id, chat_id, what, short(prompt))
    if plan.inject:
        n = queue.enqueue(plan.turn.id, prompt)
        # The work continues in the trace of the turn that is already running.
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
