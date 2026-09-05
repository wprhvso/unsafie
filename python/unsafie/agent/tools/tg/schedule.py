import logging
from datetime import UTC

from unsafie.agent.tools.base import ToolContext, error, guarded, schema, text
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.models.scheduled_task import TaskKind
from unsafie.database.repositories.schedule import ScheduleRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.scheduler import service
from unsafie.scheduler.when import WhenError, fmt_local, zone

logger = logging.getLogger(__name__)

SERVER = "tg"


@register(
    SERVER,
    "schedule_add",
    "Schedule something for later in this chat. text — what to say or do. "
    "Exactly one of: when — a moment ('18:00', 'tomorrow 09:00', '2026-09-10 12:00') or a delay "
    "('45m', '2h30m'); cron — a cron expression in the user's timezone ('0 9 * * 1-5', '@daily'); "
    "every — a repeating interval ('6h', '1d'). "
    "kind = remind (default: the text is sent to the chat as is) | task (you are woken up with this "
    "text and act, e.g. check something and report).",
    schema(["text"], text=str, when=str, cron=str, every=str, kind=str),
)
@guarded
async def schedule_add(ctx: ToolContext, args: dict) -> dict:
    kind = (args.get("kind") or "remind").lower()
    if kind not in (TaskKind.REMIND, TaskKind.TASK):
        return error("kind must be remind | task")
    given = [k for k in ("when", "cron", "every") if args.get(k)]
    if len(given) != 1:
        return error("exactly one of when, cron, every is required")
    async with SessionLocal() as session:
        origin = await UpdateRepository(session).last_message_id(ctx.turn_id)
    try:
        task = await service.add(
            bot_id=ctx.bot_id,
            chat_id=ctx.chat_id,
            user_id=ctx.user_id,
            text=args["text"],
            kind=TaskKind(kind),
            when=args.get("when"),
            cron=args.get("cron"),
            every=args.get("every"),
            origin_message_id=origin,
        )
    except WhenError as e:
        return error(str(e))
    return text(f"scheduled [{task.id}]:\n{service.describe(task, ctx.locale)}")


@register(
    SERVER,
    "schedule_list",
    "Reminders and scheduled jobs of this chat: when they fire, how often, how many times they ran.",
    schema([]),
)
@guarded
async def schedule_list(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        rows = await ScheduleRepository(session).for_chat(ctx.bot_id, ctx.chat_id)
    if not rows:
        return text("nothing is scheduled in this chat")
    return text(service.summary(rows, ctx.locale))


@register(
    SERVER,
    "schedule_remove",
    "Delete a scheduled item by id, or all=true — everything in this chat. "
    "pause=true / resume=true disables or re-enables it instead.",
    schema([], id=int, all=bool, pause=bool, resume=bool),
)
@guarded
async def schedule_remove(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        repo = ScheduleRepository(session)
        if args.get("all"):
            n = await repo.remove_all(ctx.bot_id, ctx.chat_id)
            return text(f"{n} item(s) removed")
        if not args.get("id"):
            return error("id or all=true is required")
        task = await repo.get(ctx.bot_id, ctx.chat_id, int(args["id"]))
        if task is None:
            return error(f"no item [{args['id']}] in this chat")
        if args.get("pause") or args.get("resume"):
            await repo.set_enabled(task, bool(args.get("resume")))
            return text(f"[{task.id}] {'resumed' if task.enabled else 'paused'}")
        await repo.remove(ctx.bot_id, ctx.chat_id, int(args["id"]))
    return text(f"[{args['id']}] removed")


@register(
    SERVER,
    "timezone_set",
    "Remember the user's timezone: an IANA name (Europe/Moscow, Asia/Tokyo, UTC). Everything "
    "scheduled afterwards uses it. Ask for it when the user talks about times of day.",
    schema(["timezone"], timezone=str),
)
@guarded
async def timezone_set(ctx: ToolContext, args: dict) -> dict:
    from datetime import datetime

    try:
        name = await service.set_timezone(ctx.user_id, args["timezone"])
    except WhenError as e:
        return error(str(e))
    now = fmt_local(datetime.now(UTC), zone(name))
    return text(f"timezone set to {name}, local time now {now}")
