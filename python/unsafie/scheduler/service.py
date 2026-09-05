import logging
from datetime import UTC, datetime, timedelta

from unsafie.database import SessionLocal
from unsafie.database.models.scheduled_task import ScheduledTask, TaskKind
from unsafie.database.repositories.schedule import ScheduleRepository
from unsafie.database.repositories.user import UserRepository
from unsafie.errors import OpsError
from unsafie.fluent import t
from unsafie.scheduler import cron as cronlib
from unsafie.scheduler.when import WhenError, absolute, duration, fmt_local, humanize, zone
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class ScheduleError(OpsError):
    pass


async def timezone_of(user_id: int) -> str:
    async with SessionLocal() as session:
        user = await UserRepository(session).get(user_id)
    return (user.timezone if user and user.timezone else settings.default_timezone) or "UTC"


async def set_timezone(user_id: int, name: str) -> str:
    tz = zone(name)
    async with SessionLocal() as session:
        users = UserRepository(session)
        user = await users.get_or_create(user_id)
        user.timezone = tz.key
        await session.commit()
    logger.info("user=%s timezone -> %s", user_id, tz.key)
    return tz.key


def next_run(
    *,
    tz_name: str,
    when: str | None,
    cron: str | None,
    every: str | None,
    after: datetime | None = None,
) -> tuple[datetime, str | None, int | None]:
    tz = zone(tz_name)
    now = after or datetime.now(UTC)
    if cron:
        parsed = cronlib.parse(cron)
        local = now.astimezone(tz)
        upcoming = parsed.next_after(local.replace(tzinfo=None))
        return upcoming.replace(tzinfo=tz).astimezone(UTC), parsed.expr, None
    if every:
        seconds = duration(every)
        if seconds < settings.schedule_min_interval:
            raise ScheduleError(
                f"the minimum interval is {settings.schedule_min_interval}s "
                f"({humanize(settings.schedule_min_interval)})"
            )
        return now + timedelta(seconds=seconds), None, seconds
    if not when:
        raise ScheduleError("when, cron or every is required")
    text = when.strip()
    if text.lower().startswith(("in ", "через ", "+")):
        text = text.split(maxsplit=1)[1] if " " in text else text.lstrip("+")
        return now + timedelta(seconds=duration(text)), None, None
    try:
        return now + timedelta(seconds=duration(text)), None, None
    except WhenError:
        pass
    return absolute(text, tz, now), None, None


async def add(
    *,
    bot_id: int,
    chat_id: int,
    user_id: int,
    text: str,
    kind: TaskKind,
    when: str | None,
    cron: str | None,
    every: str | None,
    origin_message_id: int | None,
) -> ScheduledTask:
    if not (text or "").strip():
        raise ScheduleError("the task text is empty")
    tz_name = await timezone_of(user_id)
    try:
        run_at, cron_expr, interval = next_run(tz_name=tz_name, when=when, cron=cron, every=every)
    except (WhenError, cronlib.CronError) as e:
        raise ScheduleError(str(e)) from None
    async with SessionLocal() as session:
        repo = ScheduleRepository(session)
        if await repo.count_for_chat(bot_id, chat_id) >= settings.schedule_max_per_chat:
            raise ScheduleError(
                f"this chat already has {settings.schedule_max_per_chat} tasks; delete some first"
            )
        return await repo.add(
            bot_id=bot_id,
            chat_id=chat_id,
            user_id=user_id,
            kind=kind,
            text=text.strip(),
            tz=tz_name,
            cron=cron_expr,
            interval_sec=interval,
            next_run_at=run_at,
            origin_message_id=origin_message_id,
        )


async def advance(task: ScheduledTask) -> datetime | None:
    if not task.recurring:
        return None
    try:
        run_at, _, _ = next_run(
            tz_name=task.tz,
            when=None,
            cron=task.cron,
            every=str(task.interval_sec) + "s" if task.interval_sec else None,
            after=datetime.now(UTC),
        )
    except (WhenError, cronlib.CronError, ScheduleError):
        logger.exception("task=%s cannot compute the next run", task.id)
        return None
    return run_at


def describe(task: ScheduledTask, locale: str | None = None) -> str:
    tz = zone(task.tz)
    bits = [fmt_local(task.next_run_at, tz)]
    left = (task.next_run_at - datetime.now(UTC)).total_seconds()
    if left > 0:
        bits.append(t("tasks-in", locale, left=humanize(int(left))))
    else:
        bits.append(t("tasks-now", locale))
    if task.cron:
        bits.append(t("tasks-cron", locale, expr=task.cron))
    elif task.interval_sec:
        bits.append(t("tasks-every", locale, interval=humanize(task.interval_sec)))
    if task.runs:
        bits.append(t("tasks-runs", locale, n=task.runs))
    if not task.enabled:
        bits.append(t("tasks-paused", locale))
    mark = "⏰" if task.kind == TaskKind.REMIND else "🤖"
    return f"[{task.id}] {mark} " + " · ".join(bits) + f"\n    {task.text}"


def summary(tasks: list[ScheduledTask], locale: str | None = None) -> str:
    if not tasks:
        return t("tasks-empty", locale)
    return "\n".join(describe(x, locale) for x in tasks)
