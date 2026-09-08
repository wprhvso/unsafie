import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from unsafie.api.routes.cli.deps import Automation
from unsafie.database import SessionLocal
from unsafie.database.models.scheduled_task import ScheduledTask, TaskKind
from unsafie.database.models.ssh_watch import SshWatch, WatchMode
from unsafie.database.repositories.schedule import ScheduleRepository
from unsafie.database.repositories.subscription import SubscriptionRepository
from unsafie.database.repositories.watch import WatchRepository
from unsafie.errors import OpsError
from unsafie.github import subscriptions
from unsafie.github.errors import GithubError
from unsafie.scheduler import service as schedules
from unsafie.scheduler.when import WhenError, duration
from unsafie.settings import settings
from unsafie.ssh import binding
from unsafie.ssh import watches as conditions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cli"])


class ScheduleIn(BaseModel):
    text: str
    when: str | None = None
    cron: str | None = None
    every: str | None = None
    task: bool = False


class WatchIn(BaseModel):
    name: str
    command: str
    condition: str
    every: str
    host: str | None = None
    task: bool = False


class SubIn(BaseModel):
    kind: str
    repo: str
    filters: dict | None = None


def _task(row: ScheduledTask) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "text": row.text,
        "cron": row.cron,
        "every": row.interval_sec,
        "next_run_at": row.next_run_at,
        "runs": row.runs,
        "enabled": row.enabled,
        "tz": row.tz,
    }


def _watch(row: SshWatch, host) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "host": host.alias if host else None,
        "command": row.command,
        "condition": row.condition,
        "every": row.interval_sec,
        "mode": row.mode,
        "alerting": row.alerting,
        "enabled": row.enabled,
        "last_run_at": row.last_run_at,
        "last_exit": row.last_exit,
    }


def _chat(who: Automation) -> tuple[int, int]:
    if who.bot_id is None:
        raise HTTPException(400, "this token is not bound to a bot")
    return who.bot_id, who.chat()


@router.get("/schedule")
async def schedule_list(who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        rows = await ScheduleRepository(session).for_chat(bot_id, chat_id)
    return {"tasks": [_task(row) for row in rows]}


@router.post("/schedule")
async def schedule_add(body: ScheduleIn, who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    try:
        row = await schedules.add(
            bot_id=bot_id,
            chat_id=chat_id,
            user_id=who.user_id,
            text=body.text,
            kind=TaskKind.TASK if body.task else TaskKind.REMIND,
            when=body.when,
            cron=body.cron,
            every=body.every,
            origin_message_id=None,
        )
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    return {"task": _task(row)}


@router.delete("/schedule/{task_id}")
async def schedule_rm(task_id: int, who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        gone = await ScheduleRepository(session).remove(bot_id, chat_id, task_id)
    if not gone:
        raise HTTPException(404, "no such task in this chat")
    return {"id": task_id, "removed": True}


@router.post("/schedule/{task_id}/pause")
async def schedule_pause(task_id: int, who: Automation, on: bool = False) -> dict:
    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        repository = ScheduleRepository(session)
        row = await repository.get(bot_id, chat_id, task_id)
        if row is None:
            raise HTTPException(404, "no such task in this chat")
        await repository.set_enabled(row, on)
        return {"task": _task(row)}


@router.get("/watch")
async def watch_list(who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        rows = await WatchRepository(session).for_chat(bot_id, chat_id)
    return {"watches": [_watch(watch, host) for watch, host in rows]}


@router.post("/watch")
async def watch_add(body: WatchIn, who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    try:
        host = await binding.resolve(who.user_id, body.host)
        condition = conditions.parse(body.condition)
        every = int(duration(body.every))
    except (OpsError, WhenError) as refused:
        raise HTTPException(400, str(refused)) from None
    if every < settings.watch_min_interval:
        raise HTTPException(400, f"the minimum interval is {settings.watch_min_interval}s")
    async with SessionLocal() as session:
        repository = WatchRepository(session)
        if await repository.count_for_chat(bot_id, chat_id) >= settings.watch_max_per_chat:
            raise HTTPException(409, "this chat already has as many watches as it may have")
        row = await repository.add(
            bot_id=bot_id,
            chat_id=chat_id,
            user_id=who.user_id,
            host_id=host.id,
            name=body.name[:128],
            command=body.command,
            condition=condition.raw,
            interval_sec=every,
            mode=WatchMode.TASK if body.task else WatchMode.NOTIFY,
            next_run_at=datetime.now(UTC) + timedelta(seconds=5),
        )
    return {"watch": _watch(row, host)}


@router.delete("/watch/{watch_id}")
async def watch_rm(watch_id: int, who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        gone = await WatchRepository(session).remove(bot_id, chat_id, watch_id)
    if not gone:
        raise HTTPException(404, "no such watch in this chat")
    return {"id": watch_id, "removed": True}


@router.post("/watch/{watch_id}/run")
async def watch_run(watch_id: int, who: Automation) -> dict:
    from unsafie.ssh.watchdog import run_once

    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        found = await WatchRepository(session).for_chat(bot_id, chat_id)
    pair = next((item for item in found if item[0].id == watch_id), None)
    if pair is None:
        raise HTTPException(404, "no such watch in this chat")
    watch, host = pair
    try:
        fires, reason, result = await run_once(watch, host)
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    return {
        "watch": _watch(watch, host),
        "fires": fires,
        "reason": reason,
        "exit_code": result.exit_code if result else None,
        "output": (result.output if result else "")[: settings.ssh_max_output],
    }


@router.get("/subs")
async def sub_list(who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        rows = await SubscriptionRepository(session).for_chat(bot_id, chat_id)
    return {
        "subs": [
            {
                "id": sub.id,
                "kind": sub.kind,
                "repo": f"{repo.owner}/{repo.name}",
                "filters": sub.filters,
            }
            for sub, repo in rows
        ]
    }


@router.post("/subs")
async def sub_add(body: SubIn, who: Automation) -> dict:
    from unsafie.github import pat

    bot_id, chat_id = _chat(who)
    if not subscriptions.valid_kind(body.kind):
        raise HTTPException(400, f"unknown kind '{body.kind}'")
    try:
        repo, _ = await pat.add(who.user_id, body.repo)
    except (GithubError, OpsError) as refused:
        raise HTTPException(400, str(refused)) from None
    async with SessionLocal() as session:
        sub = await SubscriptionRepository(session).add(
            bot_id, chat_id, who.user_id, repo.id, body.kind, body.filters or {}
        )
    return {"id": sub.id, "kind": sub.kind, "repo": f"{repo.owner}/{repo.name}"}


@router.delete("/subs/{sub_id}")
async def sub_rm(sub_id: int, who: Automation) -> dict:
    bot_id, chat_id = _chat(who)
    async with SessionLocal() as session:
        gone = await SubscriptionRepository(session).remove(bot_id, chat_id, sub_id)
    if not gone:
        raise HTTPException(404, "no such subscription in this chat")
    return {"id": sub_id, "removed": True}


@router.get("/tz")
async def tz_get(who: Automation) -> dict:
    return {"timezone": await schedules.timezone_of(who.user_id)}


@router.post("/tz")
async def tz_set(who: Automation, zone: str) -> dict:
    try:
        return {"timezone": await schedules.set_timezone(who.user_id, zone)}
    except (OpsError, WhenError) as refused:
        raise HTTPException(400, str(refused)) from None
