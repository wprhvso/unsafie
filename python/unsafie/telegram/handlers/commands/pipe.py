import asyncio
import logging
from uuid import UUID

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.agent import queue, turns
from unsafie.agent.runtime import _ACTIVE_TURNS, prompt_for, run_turn
from unsafie.database import SessionLocal
from unsafie.database.models.turn import TurnStatus
from unsafie.database.repositories.turn import TurnRepository
from unsafie.telegram.handlers.locale import locale_for

logger = logging.getLogger(__name__)

_ACTIVE_PIPELINES: dict[tuple[int, int], tuple[int, asyncio.Task]] = {}


def cancel_pipeline(bot_id: int, chat_id: int, user_id: int | None = None) -> bool:
    entry = _ACTIVE_PIPELINES.get((bot_id, chat_id))
    if entry is None:
        return False
    owner_id, task = entry
    if user_id is not None and owner_id != user_id:
        return False
    _ACTIVE_PIPELINES.pop((bot_id, chat_id), None)
    if not task.done():
        task.cancel()
        return True
    return False


async def _run_pipe(
    bot: Bot,
    message: Message,
    bot_id: int,
    user_id: int,
    chat_id: int,
    lines: list[str],
    update_db_id: int | None,
    locale: str,
) -> None:
    parent_turn_id: UUID | None = None
    reply_to = message.reply_to_message.message_id if message.reply_to_message else None
    try:
        for idx, line in enumerate(lines):
            step_msg = message.model_copy(
                update={
                    "text": line,
                    "caption": None,
                    "entities": None,
                    "caption_entities": None,
                    "reply_to_message": message.reply_to_message if idx == 0 else None,
                },
            ).as_(bot)
            step_update_id = update_db_id if idx == 0 else None
            plan = await turns.route(
                bot_id=bot_id,
                chat_id=chat_id,
                user_id=user_id,
                reply_to=reply_to if idx == 0 else None,
                update_db_id=step_update_id,
                parent_turn_id=parent_turn_id,
            )
            if plan.inject:
                prompt = prompt_for(step_msg, plan.in_context)
                await queue.enqueue(plan.turn.id, prompt)
                logger.info("pipe step=%d queued into turn=%s", idx, plan.turn.id)
                break

            prompt = prompt_for(step_msg, plan.in_context)
            await run_turn(bot, plan, prompt, locale)

            async with SessionLocal() as session:
                turn_row = await TurnRepository(session).get(plan.turn.id)
            if turn_row is None or turn_row.status != TurnStatus.DONE:
                logger.info(
                    "pipe stopped at step=%d turn=%s status=%s",
                    idx,
                    plan.turn.id,
                    turn_row.status if turn_row else "missing",
                )
                break
            parent_turn_id = plan.turn.id
    except asyncio.CancelledError:
        logger.info("pipe cancelled bot=%s chat=%s", bot_id, chat_id)
    except Exception:
        logger.exception("pipe crashed bot=%s chat=%s", bot_id, chat_id)
    finally:
        _ACTIVE_PIPELINES.pop((bot_id, chat_id), None)


def build_pipe_router() -> Router:
    router = Router()

    @router.message(Command("pipe"))
    async def pipe_handler(
        message: Message,
        command: CommandObject,
        bot_id: int,
        update_db_id: int | None = None,
    ) -> None:
        if message.from_user is None or message.bot is None:
            return
        raw = (command.args or "").strip()
        if not raw:
            return
        parts = raw.split("\n") if "\n" in raw else (raw.split("\\n") if "\\n" in raw else [raw])
        lines = [p.strip() for p in parts if p.strip()]
        if not lines:
            return

        user_id = message.from_user.id
        chat_id = message.chat.id
        locale = await locale_for(user_id, message.from_user)

        cancel_pipeline(bot_id, chat_id)

        task = asyncio.create_task(
            _run_pipe(
                message.bot,
                message,
                bot_id,
                user_id,
                chat_id,
                lines,
                update_db_id,
                locale,
            ),
            name=f"pipe:{bot_id}:{chat_id}",
        )
        _ACTIVE_PIPELINES[(bot_id, chat_id)] = (user_id, task)
        _ACTIVE_TURNS.add(task)
        task.add_done_callback(_ACTIVE_TURNS.discard)

    return router
