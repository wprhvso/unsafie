import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select

from unsafie import cluster, tokens
from unsafie.database import SessionLocal
from unsafie.database.models.api_token import TokenKind
from unsafie.database.models.pool import MachineState, PoolLease, PoolMachine
from unsafie.database.models.user import User
from unsafie.errors import OpsError
from unsafie.pool import channel, keys, registry
from unsafie.settings import settings
from unsafie_wire import channel as wire

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
    if await spent_today(user_id) >= user.pool_max_machines_day:
        raise PoolError(
            f"you have used {user.pool_max_machines_day} machines today, which is the daily limit"
        )
    wanted = min(count, room)
    deadline = time.monotonic() + (settings.pool_take_wait if wait is None else wait)
    taken: list[PoolMachine] = []
    aliases = {m.alias for m in mine if m.alias}
    await _queue_up(user_id)
    while len(taken) < wanted:
        name = await registry.grab_idle() if await _my_turn(user_id) else None
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
    await _leave_queue(user_id)
    if not taken:
        ahead = await _ahead_of(user_id)
        raise PoolError(
            "no free machine right now"
            + (f", {ahead} user(s) are waiting before you" if ahead else "")
            + ". The keeper is bringing more up; try again in a few seconds."
        )
    return taken


async def _queue_up(user_id: int) -> None:
    await cluster.client().zadd(keys.pending(), {str(user_id): time.time()}, nx=True)


async def _leave_queue(user_id: int) -> None:
    await cluster.client().zrem(keys.pending(), str(user_id))


async def _waiting() -> list[int]:
    redis = cluster.client()
    await redis.zremrangebyscore(keys.pending(), 0, time.time() - settings.pool_take_wait * 3)
    rows = await redis.zrange(keys.pending(), 0, -1)
    out: list[int] = []
    for row in rows:
        try:
            out.append(int(row))
        except ValueError:
            continue
    return out


async def _holdings() -> dict[int, int]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(PoolMachine.user_id, func.count())
            .where(PoolMachine.state == MachineState.LEASED, PoolMachine.gone_at.is_(None))
            .group_by(PoolMachine.user_id)
        )
        return {int(user_id): int(count) for user_id, count in rows if user_id is not None}


async def _order() -> list[int]:
    waiting = await _waiting()
    if len(waiting) < 2:
        return waiting
    holdings = await _holdings()
    return sorted(waiting, key=lambda user_id: (holdings.get(user_id, 0), waiting.index(user_id)))


async def _my_turn(user_id: int) -> bool:
    order = await _order()
    return not order or order[0] == user_id


async def _ahead_of(user_id: int) -> int:
    order = await _order()
    return order.index(user_id) if user_id in order else 0


async def spent_today(user_id: int) -> int:
    async with SessionLocal() as session:
        used = await session.scalar(
            select(func.count())
            .select_from(PoolLease)
            .where(PoolLease.user_id == user_id, PoolLease.taken_at >= _midnight())
        )
    return int(used or 0)


def _midnight() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


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
    if time.monotonic() - registry.BOOTED < settings.pool_machine_ttl:
        return 0
    released = 0
    idle_limit = settings.pool_lease_idle
    await _close_stray_leases()
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


async def _close_stray_leases() -> int:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(PoolLease, PoolMachine.gone_reason)
            .join(PoolMachine, PoolMachine.name == PoolLease.machine)
            .where(PoolLease.released_at.is_(None), PoolMachine.gone_at.is_not(None))
        )
        closed = 0
        now = datetime.now(UTC)
        for lease, reason in rows:
            lease.released_at = now
            lease.reason = (reason or "machine gone")[:64]
            lease.seconds = (now - lease.taken_at).total_seconds()
            closed += 1
        if closed:
            await session.commit()
            logger.info("pool: %s lease(s) closed behind machines that had gone", closed)
        return closed


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
