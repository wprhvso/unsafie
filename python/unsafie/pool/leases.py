import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from unsafie_wire import channel as wire

from unsafie import tokens
from unsafie.database import SessionLocal
from unsafie.database.models.api_token import TokenKind
from unsafie.database.models.pool import MachineState, PoolLease, PoolMachine
from unsafie.database.models.user import User
from unsafie.errors import OpsError
from unsafie.pool import channel, registry
from unsafie.settings import settings

logger = logging.getLogger(__name__)

POLL = 1.0


class PoolError(OpsError):
    pass


def _alias(taken: set[str]) -> str:
    index = 1
    while f"box-{index}" in taken:
        index += 1
    return f"box-{index}"


async def _limits(user_id: int) -> User:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


async def take(
    user_id: int,
    chat_id: int | None,
    count: int = 1,
    wait: float | None = None,
    turn_id: UUID | None = None,
    bot_id: int | None = None,
) -> list[PoolMachine]:
    if not settings.pool_enabled:
        raise PoolError("the pool is switched off on this server")
    user = await _limits(user_id)
    if user.pool_blocked:
        raise PoolError("your access to the pool is blocked")
    mine = await registry.of_user(user_id)
    room = user.pool_max_machines - len(mine)
    if room <= 0:
        raise PoolError(
            f"you already hold {len(mine)} machine(s), the limit is {user.pool_max_machines}. "
            "Release one: unsafie release box-N"
        )
    wanted = min(count, room)
    deadline = time.monotonic() + (settings.pool_take_wait if wait is None else wait)
    taken: list[PoolMachine] = []
    aliases = {m.alias for m in mine if m.alias}
    while len(taken) < wanted:
        name = await registry.grab_idle()
        if name is None:
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(POLL)
            continue
        alias = _alias({a for a in aliases if a})
        machine = await _bind(name, user_id, chat_id, alias, turn_id, bot_id)
        if machine is None:
            continue
        aliases.add(alias)
        taken.append(machine)
    if not taken:
        free = await registry.idle_count()
        raise PoolError(
            "no free machine right now"
            + (f" ({free} idle but they went away)" if free else "")
            + ". The keeper is bringing more up; try again in a few seconds."
        )
    return taken


async def _bind(
    name: str,
    user_id: int,
    chat_id: int | None,
    alias: str,
    turn_id: UUID | None,
    bot_id: int | None,
) -> PoolMachine | None:
    async with SessionLocal() as session:
        machine = await session.scalar(select(PoolMachine).where(PoolMachine.name == name))
        if machine is None or machine.gone_at is not None:
            return None
        machine.state = MachineState.LEASED
        machine.user_id = user_id
        machine.chat_id = chat_id
        machine.alias = alias
        machine.leased_at = datetime.now(UTC)
        session.add(
            PoolLease(machine=name, user_id=user_id, chat_id=chat_id, turn_id=turn_id)
        )
        await session.commit()
        await session.refresh(machine)
    await registry.mark(name, MachineState.LEASED)
    _, raw = await tokens.issue(
        user_id=user_id,
        bot_id=bot_id,
        chat_id=chat_id,
        name=f"machine {alias}",
        kind=TokenKind.MACHINE,
        machine=name,
    )
    await channel.tell(
        name,
        wire.assign(
            raw,
            chat_id=chat_id,
            user_id=user_id,
            alias=alias,
            turn=str(turn_id) if turn_id else None,
        ),
    )
    logger.info("pool %s leased to user=%s as %s", name, user_id, alias)
    return machine


async def release(user_id: int, ref: str | None, reason: str = "released") -> list[str]:
    mine = await registry.of_user(user_id)
    if not mine:
        return []
    if ref in (None, "", "all"):
        targets = mine
    else:
        found = [m for m in mine if ref in (m.alias, m.name)]
        if not found:
            known = ", ".join(m.alias or m.name for m in mine)
            raise PoolError(f"no machine '{ref}'. Yours: {known}")
        targets = found
    gone: list[str] = []
    for machine in targets:
        await destroy(machine.name, reason)
        gone.append(machine.alias or machine.name)
    return gone


async def destroy(name: str, reason: str) -> None:
    await channel.tell(name, wire.shutdown(reason))
    await tokens.revoke_machine(name)
    await _close_lease(name, reason)
    await registry.forget(name, reason)


async def _close_lease(name: str, reason: str) -> None:
    async with SessionLocal() as session:
        lease = await session.scalar(
            select(PoolLease)
            .where(PoolLease.machine == name, PoolLease.released_at.is_(None))
            .order_by(PoolLease.id.desc())
        )
        if lease is None:
            return
        now = datetime.now(UTC)
        lease.released_at = now
        lease.reason = reason[:64]
        lease.seconds = (now - lease.taken_at).total_seconds()
        await session.commit()


async def rename(name: str, alias: str) -> None:
    async with SessionLocal() as session:
        machine = await session.scalar(select(PoolMachine).where(PoolMachine.name == name))
        if machine is None:
            return
        machine.alias = alias
        await session.commit()


async def resolve(user_id: int, ref: str | None) -> PoolMachine:
    mine = await registry.of_user(user_id)
    if ref:
        for machine in mine:
            if ref in (machine.alias, machine.name):
                return machine
        known = ", ".join(m.alias or m.name for m in mine) or "none"
        raise PoolError(f"no machine '{ref}'. Yours: {known}")
    if not mine:
        raise PoolError("you have no machine; take one with `unsafie take`")
    return mine[0]


async def ensure(
    user_id: int,
    chat_id: int | None,
    turn_id: UUID | None = None,
    bot_id: int | None = None,
) -> PoolMachine:
    mine = await registry.of_user(user_id)
    if mine:
        return mine[0]
    taken = await take(user_id, chat_id, 1, turn_id=turn_id, bot_id=bot_id)
    return taken[0]


async def reap() -> int:
    released = 0
    idle_limit = settings.pool_lease_idle
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(PoolMachine).where(
                PoolMachine.state == MachineState.LEASED, PoolMachine.gone_at.is_(None)
            )
        )
        machines = list(rows)
    now = datetime.now(UTC)
    for machine in machines:
        if not await registry.alive(machine.name):
            await _close_lease(machine.name, "machine gone")
            await registry.forget(machine.name, "no heartbeat")
            released += 1
            continue
        quiet = (now - (await _last_seen(machine))).total_seconds()
        if machine.user_id and quiet > idle_limit and not await _busy(machine.name):
            await release(machine.user_id, machine.name, "idle")
            released += 1
    return released


async def _last_seen(machine: PoolMachine) -> datetime:
    from unsafie.database.models.pool import PoolCommand

    async with SessionLocal() as session:
        latest = await session.scalar(
            select(PoolCommand.created_at)
            .where(PoolCommand.machine == machine.name)
            .order_by(PoolCommand.created_at.desc())
            .limit(1)
        )
    return latest or machine.leased_at or machine.started_at


async def _busy(name: str) -> bool:
    from unsafie.database.models.pool import CommandStatus, PoolCommand

    async with SessionLocal() as session:
        found = await session.scalar(
            select(PoolCommand.id)
            .where(
                PoolCommand.machine == name,
                PoolCommand.status.in_([CommandStatus.QUEUED, CommandStatus.RUNNING]),
            )
            .limit(1)
        )
    return found is not None
