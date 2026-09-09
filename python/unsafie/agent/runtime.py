import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ChosenInlineResult, InlineKeyboardMarkup, Message

from unsafie import events, telemetry
from unsafie.agent import (
    cancel,
    checkpoints,
    credentials,
    live,
    loop,
    opal,
    queue,
    request,
    segments,
    turns,
)
from unsafie.agent.prompt import SUBAGENT_SYSTEM_PROMPT, SYSTEM_PROMPT
from unsafie.agent.prompt.context import build_context
from unsafie.agent.session import Ctx
from unsafie.agent.subagents import (
    cancel_subagents_of,
    notify_subagent_done,
    register_subagent_task,
)
from unsafie.agent.trace import Recorder
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.models.turn import Turn, TurnStatus
from unsafie.database.repositories.opal_session import OpalSessionRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.log import short
from unsafie.settings import settings
from unsafie.telegram import bots, render, sender
from unsafie.telegram.chat_action import typing
from unsafie.telegram.retry import retry_markup
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
        },
    )


async def _punish(session_row, result: loop.Result) -> None:
    await opal.invalidate(session_row.id)
    async with SessionLocal() as session:
        creds = OpalSessionRepository(session)
        row = await creds.get(session_row.id)
        if row is None:
            return
        cooldown = credentials.cooldown_for(row.failures + 1, result.failure)
        disable = result.failure == credentials.Failure.AUTH
        await creds.failed(
            session_row.id, error=result.error or "", cooldown_until=cooldown, disable=disable
        )
    events.publish(
        "credential.failed",
        credential_id=session_row.id,
        failure=str(result.failure),
        cooldown_until=cooldown.isoformat() if cooldown else None,
        disabled=disable,
    )


async def _execute(
    ctx: Ctx,
    messages: list[dict],
    system_prompt: str,
    initial_checkpoint: checkpoints.CheckpointData | None = None,
) -> Outcome:
    prefix = ctx.prefix
    tried: set[int] = set()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        with telemetry.span(
            "agent.attempt",
            attributes={attrs.ATTEMPT: attempt, attrs.TURN_ID: str(ctx.turn_id)},
        ) as attempt_span:
            async with SessionLocal() as session:
                creds = OpalSessionRepository(session)
                session_row = await creds.pick(tried)
                if session_row is None:
                    next_at = await creds.next_cooldown()
                    telemetry.refused(
                        attempt_span, f"no usable opal session (tried={sorted(tried)})"
                    )
                    logger.warning("%s no usable opal session (tried=%s)", prefix, sorted(tried))
                    return Outcome("no_credentials", next_at=next_at)
                user = await UserRepository(session).get_or_create(ctx.user_id)
                model = settings.gemini_model
                effort = user.effort or settings.gemini_thinking_level

            try:
                access_token = await opal.get_access_token(
                    session_row.id, session_row.refresh_token
                )
            except opal.OpalRefreshFailed as e:
                logger.warning("%s opal session %s refresh failed: %s", prefix, session_row.id, e)
                tried.add(session_row.id)
                await _punish(
                    session_row,
                    loop.Result(status="failed", error=str(e), failure=credentials.Failure.AUTH),
                )
                continue

            telemetry.set_attrs(
                attempt_span,
                {
                    attrs.CREDENTIAL_ID: session_row.id,
                    attrs.GEN_AI_MODEL: model,
                    attrs.EFFORT: effort,
                },
            )
            logger.info(
                "%s attempt=%s session=%s model=%s effort=%s messages=%s",
                prefix,
                attempt,
                session_row.id,
                model,
                effort,
                len(messages),
            )

            live.emit(
                ctx.turn_id,
                "attempt.start",
                attempt=attempt,
                model=model,
                effort=effort,
            )
            started = time.perf_counter()
            with telemetry.span(
                "gen_ai.invoke_agent",
                kind=telemetry.CLIENT,
                attributes={
                    attrs.GEN_AI_SYSTEM: "gemini",
                    attrs.GEN_AI_OPERATION: "invoke_agent",
                    attrs.GEN_AI_MODEL: model,
                    attrs.EFFORT: effort,
                    attrs.TURN_ID: str(ctx.turn_id),
                },
            ) as query_span:
                result = await loop.run(
                    ctx,
                    messages=messages,
                    access_token=access_token,
                    model=model,
                    prompt=system_prompt,
                    effort=effort,
                    recorder=Recorder(prefix, live.of(ctx.turn_id)),
                    credential_id=session_row.id,
                    initial_checkpoint=initial_checkpoint,
                )
                elapsed = (time.perf_counter() - started) * 1000
                _usage(query_span, result)
                telemetry.set_attrs(
                    query_span,
                    {
                        attrs.SDK_MESSAGES: len(messages),
                        attrs.NUM_TURNS: result.steps,
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

            async with SessionLocal() as session:
                await TurnRepository(session).record(
                    ctx.turn_id,
                    credential_id=session_row.id,
                    num_turns=result.steps,
                    result=result.text,
                )

            telemetry.set_attrs(
                attempt_span,
                {
                    attrs.OUTCOME: result.status,
                    attrs.NUM_TURNS: result.steps,
                    attrs.FAILURE: str(result.failure) if result.failure else None,
                },
            )
            logger.info(
                "%s attempt=%s %s steps=%s in %.1fms",
                prefix,
                attempt,
                result.status,
                result.steps,
                elapsed,
            )

            live.emit(
                ctx.turn_id,
                "attempt.end",
                attempt=attempt,
                status=result.status,
                steps=result.steps,
                usage=result.usage,
                stop_reason=result.stop_reason,
                error=short(result.error, 300) if result.error else None,
            )

            initial_checkpoint = None
            if result.status == "ok":
                async with SessionLocal() as session:
                    await OpalSessionRepository(session).succeeded(session_row.id)
                return Outcome("ok")
            if result.failure is not None and credentials.blames_credential(result.failure):
                logger.warning(
                    "%s session=%s failed (%s): %s",
                    prefix,
                    session_row.id,
                    result.failure,
                    short(result.error, 600),
                )
                tried.add(session_row.id)
                await _punish(session_row, result)
                continue
            return Outcome("failed", error=result.error)
    return Outcome("failed", error="attempts exhausted")


async def notify(
    bot: Bot, turn: Turn, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    try:
        await sender.send(
            bot,
            bot_id=turn.bot_id,
            chat_id=turn.chat_id,
            markdown=text,
            kind=ResponseKind.SYSTEM,
            turn=turn,
            reply_markup=reply_markup,
        )
    except TelegramAPIError as e:
        logger.error(
            "bot=%s chat=%s turn=%s notify failed error=%s", turn.bot_id, turn.chat_id, turn.id, e
        )


def _failure_text(locale: str, outcome: Outcome) -> str:
    if outcome.status == "no_credentials":
        when = ""
        if outcome.next_at is not None:
            minutes = max(1, int((outcome.next_at - datetime.now(UTC)).total_seconds() // 60) + 1)
            when = t("agent-no-credentials-when", locale, minutes=minutes)
        return t("agent-no-credentials", locale, when=when)
    return t("agent-failure", locale)


async def run_turn(bot: Bot, plan: turns.Plan, prompt: str, locale: str) -> None:
    turn = plan.turn
    ctx = Ctx(
        bot,
        turn.bot_id,
        turn.chat_id,
        turn.user_id,
        turn.id,
        locale,
        inline_message_id=turn.inline_message_id,
    )
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
                        context = await build_context(session, ctx)
                messages.append(request.user(prompt, context))
                while True:
                    outcome = await _execute(ctx, messages, system_prompt)
                    if outcome.status != "ok":
                        await queue.clear(turn.id)
                        note = (
                            outcome.status if outcome.error is None else short(outcome.error, 1000)
                        )
                        logger.info("%s finished with %s", prefix, outcome.status)
                        await notify(
                            bot,
                            turn,
                            _failure_text(locale, outcome),
                            reply_markup=retry_markup(str(turn.id), locale),
                        )
                        return
                    leftover = await turns.finish_or_continue(turn.id, turn.bot_id, turn.chat_id)
                    if leftover is None:
                        status = TurnStatus.DONE
                        return
                    messages.append(request.user(leftover))
                    telemetry.event("unsafie.turn_rerun")
                    logger.info("%s re-running with messages that arrived after the reply", prefix)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            status = TurnStatus.CANCELLED
            note = "stopped by the user"
            logger.info("%s stopped by the user", prefix)
            await queue.clear(turn.id)
            await notify(bot, turn, t("agent-stopped", locale))
        except Exception as e:
            telemetry.fail(turn_span, e)
            logger.exception("%s turn crashed", prefix)
            await queue.clear(turn.id)
            note = "crashed"
            await notify(
                bot,
                turn,
                t("agent-failure", locale),
                reply_markup=retry_markup(str(turn.id), locale),
            )
        finally:
            await cancel_subagents_of(turn.id)
            await cancel.clear(turn.id)
            await turns.seal(turn.id)
            await segments.save(turn, messages[base:], snapshot)
            async with SessionLocal() as session:
                await TurnRepository(session).finish(turn.id, status, note)
                fresh = await TurnRepository(session).get(turn.id)
            telemetry.set_attrs(
                turn_span,
                {
                    attrs.TURN_STATUS: str(status),
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
                note=note,
            )
            live.emit(
                turn.id,
                "turn.end",
                status=str(status),
                steps=fresh.num_turns if fresh else 0,
                note=note,
            )
            await live.end(turn.id)


async def run_subagent_turn(turn_id: UUID, prompt: str, timeout: float = 600.0) -> None:
    async with SessionLocal() as session:
        turn = await TurnRepository(session).get(turn_id)
        if turn is None:
            logger.error("subagent turn=%s not found", turn_id)
            return
        user = await UserRepository(session).get(turn.user_id)
        locale = user.locale if user and user.locale else settings.default_locale

    bot = await bots.bot_for(turn.bot_id)
    if bot is None:
        logger.error("subagent turn=%s bot=%s not found", turn_id, turn.bot_id)
        return

    ctx = Ctx(bot, turn.bot_id, turn.chat_id, turn.user_id, turn.id, locale)
    prefix = f"[subagent] {ctx.prefix}"
    system_prompt = SUBAGENT_SYSTEM_PROMPT
    messages = [request.user(prompt)]

    status = TurnStatus.FAILED
    note: str | None = None
    stream = await live.begin(turn)
    if stream is not None:
        stream.emit(
            "turn.start",
            turn_id=str(turn.id),
            root_id=str(turn.root_id),
            chat_id=turn.chat_id,
            resumed=0,
            prompt=live.clip(prompt)[0],
            is_subagent=True,
            title=turn.title,
        )
    events.publish(
        "turn.started",
        turn_id=str(turn.id),
        root_id=str(turn.root_id),
        parent_id=str(turn.parent_id),
        bot_id=turn.bot_id,
        chat_id=turn.chat_id,
        user_id=turn.user_id,
        is_subagent=True,
        title=turn.title,
    )

    with telemetry.span(
        "agent.subagent_turn",
        attributes={
            attrs.TURN_ID: str(turn.id),
            attrs.ROOT_ID: str(turn.root_id),
            attrs.BOT_ID: turn.bot_id,
            attrs.CHAT_ID: turn.chat_id,
            attrs.USER_ID: turn.user_id,
            attrs.LOCALE: locale,
            "unsafie.is_subagent": True,
            "unsafie.title": turn.title or "",
        },
    ) as turn_span:
        try:
            async with turns.alive(turn.id):
                async with asyncio.timeout(timeout):
                    outcome = await _execute(ctx, messages, system_prompt)
                    if outcome.status == "ok":
                        status = TurnStatus.DONE
                    else:
                        status = TurnStatus.FAILED
                        note = outcome.error or outcome.status
        except TimeoutError:
            status = TurnStatus.FAILED
            note = f"timed out after {timeout:.0f}s"
            logger.warning("%s timed out after %.0fs", prefix, timeout)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            status = TurnStatus.CANCELLED
            note = "stopped"
            logger.info("%s stopped", prefix)
        except Exception as e:
            telemetry.fail(turn_span, e)
            logger.exception("%s subagent crashed", prefix)
            status = TurnStatus.FAILED
            note = f"crashed: {e}"
        finally:
            await cancel.clear(turn.id)
            await turns.seal(turn.id)
            await segments.save(turn, messages, snapshot=system_prompt)
            async with SessionLocal() as session:
                repo = TurnRepository(session)
                fresh = await repo.get(turn.id)
                fallback_result = None
                if messages and messages[-1].get("role") == "assistant":
                    content = messages[-1].get("content")
                    if isinstance(content, str):
                        fallback_result = content
                final_result = (
                    fresh.result if fresh and fresh.result else (fallback_result or note or "done")
                )
                await repo.finish(turn.id, status, final_result)
                fresh = await repo.get(turn.id)

            telemetry.set_attrs(
                turn_span,
                {
                    attrs.TURN_STATUS: str(status),
                    attrs.REFUSAL: note,
                },
            )
            events.publish(
                "turn.finished",
                turn_id=str(turn.id),
                root_id=str(turn.root_id),
                parent_id=str(turn.parent_id),
                bot_id=turn.bot_id,
                chat_id=turn.chat_id,
                user_id=turn.user_id,
                status=str(status),
                is_subagent=True,
                note=note,
            )
            live.emit(
                turn.id,
                "turn.end",
                status=str(status),
                steps=fresh.num_turns if fresh else 0,
                note=note,
            )
            await live.end(turn.id)
            await notify_subagent_done(turn.id)


def spawn_subagent_task(turn_id: UUID, prompt: str, timeout: float = 600.0) -> asyncio.Task:
    task = asyncio.create_task(
        run_subagent_turn(turn_id, prompt, timeout=timeout),
        name=f"subagent:{turn_id}",
    )
    register_subagent_task(turn_id, task)
    return task


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
    is_inline: bool = False,
    inline_message_id: str | None = None,
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
            is_inline=is_inline,
            inline_message_id=inline_message_id,
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
    from unsafie.database.repositories.schedule import ScheduleRepository

    prompt = json.dumps(render.describe_scheduled(task), ensure_ascii=False)
    plan = await turns.route(
        bot_id=task.bot_id,
        chat_id=task.chat_id,
        user_id=task.user_id,
        reply_to=task.origin_message_id,
        update_db_id=None,
    )
    async with SessionLocal() as session:
        await ScheduleRepository(session).bind_turn(task.id, plan.turn.id)
    await run_turn(bot, plan, prompt, settings.default_locale)


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


async def retry_turn(bot: Bot, origin: Turn, locale: str) -> None:
    async with SessionLocal() as session:
        update_repo = UpdateRepository(session)
        update_row = await update_repo.first_for_turn(origin.id)

    if update_row is not None and "message" in update_row.payload:
        msg = Message.model_validate(update_row.payload["message"])
        msg.bot = bot
        reply_to = msg.reply_to_message.message_id if msg.reply_to_message else origin.reply_to
        await dispatch(
            bot,
            bot_id=origin.bot_id,
            chat_id=origin.chat_id,
            user_id=origin.user_id,
            reply_to=reply_to,
            update_db_id=update_row.id,
            build_prompt=lambda in_context: prompt_for(msg, in_context),
            locale=locale,
            what=f"retry={origin.id}",
        )
        return

    prompt = f"Retry previous request for turn {origin.id}"
    await dispatch(
        bot,
        bot_id=origin.bot_id,
        chat_id=origin.chat_id,
        user_id=origin.user_id,
        reply_to=origin.reply_to,
        update_db_id=None,
        build_prompt=lambda _: prompt,
        locale=locale,
        what=f"retry={origin.id}",
    )


async def handle_inline(chosen: ChosenInlineResult, bot_id: int) -> None:
    if chosen.bot is None:
        return
    user_id = chosen.from_user.id
    locale = await _user_locale(user_id, chosen.from_user)
    query = chosen.query.strip()
    data = {
        "inline_query": query,
        "inline_message_id": chosen.inline_message_id,
        "from": render.user_info(chosen.from_user),
    }
    prompt = json.dumps(data, ensure_ascii=False)
    await dispatch(
        chosen.bot,
        bot_id=bot_id,
        chat_id=user_id,
        user_id=user_id,
        reply_to=None,
        update_db_id=None,
        build_prompt=lambda _: prompt,
        locale=locale,
        is_inline=True,
        inline_message_id=chosen.inline_message_id,
        what=f"inline={chosen.inline_message_id}",
    )



async def resume_turn(turn_id: UUID) -> None:
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        turn = await repo.get(turn_id)
        if turn is None or turn.status != TurnStatus.RUNNING:
            return
        user_repo = UserRepository(session)
        user = await user_repo.get(turn.user_id)
        locale = user.locale if user and user.locale else settings.default_locale

    bot = await bots.bot_for(turn.bot_id)
    if bot is None:
        logger.error("turn=%s bot=%s not found", turn.id, turn.bot_id)
        return

    ctx = Ctx(
        bot,
        turn.bot_id,
        turn.chat_id,
        turn.user_id,
        turn.id,
        locale,
        inline_message_id=turn.inline_message_id,
    )
    prefix = ctx.prefix

    async with cluster.lock(
        turns.chat_lock(turn.bot_id, turn.chat_id),
        ttl=settings.chat_lock_ttl,
        wait=settings.chat_lock_wait,
        renew=True,
    ):
        checkpoint = await checkpoints.load(turn.id)
        stream = await live.begin(turn)
        if stream is not None:
            step = checkpoint.step if checkpoint else 0
            phase = checkpoint.phase if checkpoint else "init"
            stream.emit(
                "turn.resumed",
                turn_id=str(turn.id),
                root_id=str(turn.root_id),
                chat_id=turn.chat_id,
                step=step,
                phase=phase,
            )

        history = await segments.load(turn)
        system_prompt = history.system or SYSTEM_PROMPT
        snapshot = None if history.system else system_prompt

        messages = checkpoint.messages if checkpoint else list(history.messages)
        if not messages:
            async with SessionLocal() as session:
                update_repo = UpdateRepository(session)
                update_row = await update_repo.first_for_turn(turn.id)
            if update_row is not None and "message" in update_row.payload:
                msg = Message.model_validate(update_row.payload["message"])
                prompt = prompt_for(msg, False)
            else:
                prompt = f"Resume turn {turn.id}"
            async with SessionLocal() as session:
                context = await build_context(session, ctx)
            messages = [request.user(prompt, context)]

        status = TurnStatus.FAILED
        note: str | None = None
        base = len(history.messages)

        try:
            async with turns.alive(turn.id), typing(bot, turn.chat_id, prefix):
                while True:
                    outcome = await _execute(
                        ctx,
                        messages,
                        system_prompt,
                        initial_checkpoint=checkpoint,
                    )
                    checkpoint = None
                    if outcome.status != "ok":
                        await queue.clear(turn.id)
                        note = (
                            outcome.status if outcome.error is None else short(outcome.error, 1000)
                        )
                        logger.info("%s resume finished with %s", prefix, outcome.status)
                        await notify(
                            bot,
                            turn,
                            _failure_text(locale, outcome),
                            reply_markup=retry_markup(str(turn.id), locale),
                        )
                        return
                    leftover = await turns.finish_or_continue(turn.id, turn.bot_id, turn.chat_id)
                    if leftover is None:
                        status = TurnStatus.DONE
                        return
                    messages.append(request.user(leftover))
                    logger.info("%s re-running with messages that arrived after the reply", prefix)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            status = TurnStatus.CANCELLED
            note = "stopped by the user"
            await queue.clear(turn.id)
            await notify(bot, turn, t("agent-stopped", locale))
        except Exception as e:
            logger.exception("%s resume turn crashed", prefix)
            await queue.clear(turn.id)
            note = "crashed"
            await notify(
                bot,
                turn,
                t("agent-failure", locale),
                reply_markup=retry_markup(str(turn.id), locale),
            )
        finally:
            await cancel_subagents_of(turn.id)
            await cancel.clear(turn.id)
            await turns.seal(turn.id)
            await segments.save(turn, messages[base:], snapshot)
            async with SessionLocal() as session:
                await TurnRepository(session).finish(turn.id, status, note)
                fresh = await TurnRepository(session).get(turn.id)
            await checkpoints.clear(turn.id)
            live.emit(
                turn.id,
                "turn.end",
                status=str(status),
                steps=fresh.num_turns if fresh else 0,
                note=note,
            )
            await live.end(turn.id)
