import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.errors import OpsError
from unsafie.fluent import t
from unsafie.pool import leases, registry
from unsafie.pool.ci import repos
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


def _machine_line(machine) -> str:
    where = machine.alias or machine.name
    facts = machine.facts or {}
    size = f"{facts.get('cpus', '?')} cpu, {facts.get('disk_gb', '?')} GB"
    return f"· `{where}` · {machine.state} · {size}"


async def _status(user_id: int, locale: str) -> str:
    mine = await registry.of_user(user_id)
    counts = await registry.counted()
    head = t("pool-status", locale)
    capacity = (
        f"{counts.get('idle', 0)} idle · {counts.get('leased', 0)} leased · "
        f"{counts.get('ci', 0)} on ci · {counts.get('total', 0)} alive"
    )
    if not mine:
        return f"{t('pool-empty', locale)}\n\n{capacity}"
    lines = [head, *[_machine_line(machine) for machine in mine], "", capacity]
    return "\n".join(lines)


async def _ci(user_id: int, parts: list[str], locale: str) -> str:
    action = parts[1].lower() if len(parts) > 1 else ""
    if action in ("add", "wire"):
        if len(parts) < 3:
            return t("pool-usage", locale)
        label = parts[3] if len(parts) > 3 else None
        try:
            row = await repos.add(user_id, parts[2], label)
        except OpsError as refused:
            return str(refused)
        return t("pool-ci-added", locale, slug=row.slug, label=row.label)
    if action in ("rm", "remove", "del"):
        if len(parts) < 3:
            return t("pool-usage", locale)
        gone = await repos.remove(user_id, parts[2])
        if gone is None:
            return t("pool-ci-empty", locale)
        return t("pool-ci-removed", locale, slug=gone.slug)
    rows = await repos.of_user(user_id)
    if not rows:
        return t("pool-ci-empty", locale)
    lines = [t("pool-ci-list", locale)]
    for row in rows:
        state = row.state + ("" if row.enabled else ", paused")
        lines.append(f"· `{row.slug}` → `runs-on: {row.label}` · {state}")
    return "\n".join(lines)


def build_pool_router() -> Router:
    router = Router()

    @router.message(Command("pool"))
    async def pool_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        parts = (command.args or "").split()
        action = parts[0].lower() if parts else ""

        if action in ("", "status", "ls", "list"):
            await answer(message, bot_id, await _status(user_id, locale))
            return

        if action == "take":
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            try:
                taken = await leases.take(user_id, message.chat.id, count, bot_id=bot_id)
            except OpsError as refused:
                await answer(message, bot_id, str(refused))
                return
            names = ", ".join(machine.alias or machine.name for machine in taken)
            await answer(message, bot_id, t("pool-took", locale, count=len(taken), names=names))
            return

        if action == "release":
            ref = parts[1] if len(parts) > 1 else None
            gone = await leases.release(user_id, None if ref in (None, "all") else ref)
            names = ", ".join(gone) if gone else "—"
            await answer(message, bot_id, t("pool-released", locale, names=names))
            return

        if action == "ci":
            await answer(message, bot_id, await _ci(user_id, parts, locale))
            return

        await answer(message, bot_id, t("pool-usage", locale))

    return router
