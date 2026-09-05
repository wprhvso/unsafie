import logging
from datetime import UTC, datetime, timedelta

from unsafie.agent.tools.base import ToolContext, error, guarded, schema, text
from unsafie.agent.tools.registry import register
from unsafie.agent.tools.ssh.context import SERVER
from unsafie.database import SessionLocal
from unsafie.database.models.ssh_watch import WatchMode
from unsafie.database.repositories.watch import WatchRepository
from unsafie.scheduler.when import WhenError, duration, humanize
from unsafie.settings import settings
from unsafie.ssh import binding, watches
from unsafie.ssh.errors import SshError

logger = logging.getLogger(__name__)


@register(
    SERVER,
    "watch_list",
    "Checks running on a schedule in this chat: what is watched, how often, current state.",
    schema([]),
)
@guarded
async def watch_list(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        rows = await WatchRepository(session).for_chat(ctx.bot_id, ctx.chat_id)
    if not rows:
        return text("no checks in this chat")
    return text("\n".join(watches.describe(w, h, ctx.locale) for w, h in rows))


@register(
    SERVER,
    "watch_add",
    "Watch a server on a schedule: run command every `every` and notify when condition holds. "
    "condition: '>90' / '<10' / '=0' — compare the first number in the output; 'exit != 0'; "
    "'contains:ERROR'; '!contains:ok'; 'matches:regex'; 'changed'; 'empty'; 'any'. "
    "mode = notify (default: just message the chat) | task (wake yourself up and investigate). "
    "A notification is sent once when the condition starts holding and once when it stops.",
    schema(
        ["name", "command", "condition", "every"],
        name=str,
        command=str,
        condition=str,
        every=str,
        host=str,
        mode=str,
    ),
)
@guarded
async def watch_add(ctx: ToolContext, args: dict) -> dict:
    host = await binding.resolve(ctx.user_id, args.get("host"))
    condition = watches.parse(args["condition"])
    try:
        interval = duration(args["every"])
    except WhenError as e:
        return error(str(e))
    if interval < settings.watch_min_interval:
        return error(f"the minimum interval is {settings.watch_min_interval}s")
    mode = (args.get("mode") or "notify").lower()
    if mode not in (WatchMode.NOTIFY, WatchMode.TASK):
        return error("mode must be notify | task")
    async with SessionLocal() as session:
        repo = WatchRepository(session)
        if await repo.count_for_chat(ctx.bot_id, ctx.chat_id) >= settings.watch_max_per_chat:
            return error(f"this chat already has {settings.watch_max_per_chat} checks")
        from unsafie.database.repositories.update import UpdateRepository

        origin = await UpdateRepository(session).last_message_id(ctx.turn_id)
        row = await repo.add(
            bot_id=ctx.bot_id,
            chat_id=ctx.chat_id,
            user_id=ctx.user_id,
            host_id=host.id,
            name=args["name"][:128],
            command=args["command"],
            condition=condition.raw,
            interval_sec=interval,
            mode=mode,
            origin_message_id=origin,
            next_run_at=datetime.now(UTC) + timedelta(seconds=interval),
        )
    return text(
        f"watch [{row.id}] '{row.name}' added on {host.alias}: every {humanize(interval)}, "
        f"condition {condition.raw}, mode {mode}"
    )


@register(
    SERVER,
    "watch_remove",
    "Delete a check by id, or all=true — every check in this chat. pause=true / resume=true "
    "temporarily disables or re-enables it instead.",
    schema([], id=int, all=bool, pause=bool, resume=bool),
)
@guarded
async def watch_remove(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        repo = WatchRepository(session)
        if args.get("all"):
            n = await repo.remove_all(ctx.bot_id, ctx.chat_id)
            return text(f"{n} check(s) removed")
        if not args.get("id"):
            return error("id or all=true is required")
        row = await repo.get(ctx.bot_id, ctx.chat_id, int(args["id"]))
        if row is None:
            return error(f"no check [{args['id']}] in this chat")
        if args.get("pause") or args.get("resume"):
            row.enabled = bool(args.get("resume"))
            if row.enabled:
                row.fails = 0
                row.next_run_at = datetime.now(UTC) + timedelta(seconds=row.interval_sec)
            await repo.save()
            return text(f"check [{row.id}] {'resumed' if row.enabled else 'paused'}")
        await repo.remove(ctx.bot_id, ctx.chat_id, int(args["id"]))
    return text(f"check [{args['id']}] removed")


@register(
    SERVER,
    "watch_run",
    "Run a check right now without waiting for the schedule: shows the output and whether the "
    "condition holds. Does not change the alert state.",
    schema(["id"], id=int),
)
@guarded
async def watch_run(ctx: ToolContext, args: dict) -> dict:
    from unsafie.ssh.watchdog import run_once

    async with SessionLocal() as session:
        rows = await WatchRepository(session).for_chat(ctx.bot_id, ctx.chat_id)
    pair = next(((w, h) for w, h in rows if w.id == int(args["id"])), None)
    if pair is None:
        return error(f"no check [{args['id']}] in this chat")
    watch, host = pair
    try:
        fires, reason, result = await run_once(watch, host)
    except SshError as e:
        return error(str(e))
    verdict = "fires" if fires else "does not fire"
    return text(
        f"[{watch.id}] {watch.name} on {host.alias}: {verdict} ({reason})\n"
        f"exit={result.exit_code}\n{result.output or '(no output)'}"
    )
