import json
import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.models.pool import MachineState, PoolMachine
from unsafie.pool import keys
from unsafie.settings import settings

logger = logging.getLogger(__name__)

BOOTED = time.monotonic()


def new_name() -> str:
    return "m-" + secrets.token_hex(4)


async def register(
    donor_id: int | None,
    run_id: int | None,
    facts: dict,
    boot_seconds: float | None,
) -> PoolMachine:
    name = new_name()
    async with SessionLocal() as session:
        machine = PoolMachine(
            name=name,
            donor_id=donor_id,
            run_id=run_id,
            state=MachineState.IDLE,
            facts=facts or {},
            boot_seconds=boot_seconds,
        )
        session.add(machine)
        await session.commit()
        await session.refresh(machine)
    redis = cluster.client()
    await redis.set(
        keys.machine(name),
        json.dumps({"state": MachineState.IDLE, "seen": time.time()}),
        ex=int(settings.pool_machine_ttl),
    )
    await redis.zadd(keys.idle(), {name: time.time()})
    logger.info("pool machine %s registered donor=%s run=%s", name, donor_id, run_id)
    return machine


async def revive(name: str) -> dict | None:
    row = await machine(name)
    if row is None or row.gone_at is not None:
        return None
    payload = {"state": row.state, "seen": time.time()}
    redis = cluster.client()
    await redis.set(keys.machine(name), json.dumps(payload), ex=int(settings.pool_machine_ttl))
    if row.state == MachineState.IDLE:
        await redis.zadd(keys.idle(), {name: time.time()})
    logger.info("pool machine %s revived from the database as %s", name, row.state)
    return payload


async def heartbeat(name: str, state: str | None = None) -> bool:
    redis = cluster.client()
    stored = await redis.get(keys.machine(name))
    payload = json.loads(stored) if stored is not None else await revive(name)
    if payload is None:
        return False
    payload["seen"] = time.time()
    if state:
        payload["state"] = state
    await redis.set(keys.machine(name), json.dumps(payload), ex=int(settings.pool_machine_ttl))
    return True


async def alive(name: str) -> bool:
    state = await state_of(name)
    return state is not None and state != MachineState.GONE


async def state_of(name: str) -> str | None:
    stored = await cluster.client().get(keys.machine(name))
    if stored is None:
        return None
    return str(json.loads(stored).get("state"))


async def mark(name: str, state: str) -> None:
    redis = cluster.client()
    stored = await redis.get(keys.machine(name))
    payload: dict[str, Any] = json.loads(stored) if stored else {"seen": time.time()}
    payload["state"] = state
    await redis.set(keys.machine(name), json.dumps(payload), ex=int(settings.pool_machine_ttl))
    if state == MachineState.IDLE:
        await redis.zadd(keys.idle(), {name: time.time()})
    else:
        await redis.zrem(keys.idle(), name)


async def grab_idle() -> str | None:
    redis = cluster.client()
    while True:
        found = await redis.zpopmin(keys.idle(), 1)
        if not found:
            return None
        raw_name = found[0][0]
        name = raw_name.decode() if isinstance(raw_name, bytes) else str(raw_name)
        if await alive(name):
            return name
        await forget(name, "vanished before it was taken")


async def hold(name: str, seconds: float) -> float:
    """Keep a machine alive for a while even if nobody is typing on it."""
    left = max(0.0, min(float(seconds), settings.pool_hold_max))
    redis = cluster.client()
    if left <= 0:
        await redis.delete(keys.hold(name))
        return 0.0
    await redis.set(keys.hold(name), str(time.time() + left), ex=int(left) + 1)
    return left


async def held(name: str) -> float:
    """Seconds left on the hold of a machine, 0 when it is not held."""
    left = await cluster.client().ttl(keys.hold(name))
    return float(left) if left and left > 0 else 0.0


async def idle_count() -> int:
    return int(await cluster.client().zcard(keys.idle()))


async def forget(name: str, reason: str) -> None:
    redis = cluster.client()
    await redis.zrem(keys.idle(), name)
    await redis.delete(keys.machine(name))
    await redis.delete(keys.inbox(name))
    await redis.delete(keys.hold(name))
    async with SessionLocal() as session:
        await session.execute(
            update(PoolMachine)
            .where(PoolMachine.name == name, PoolMachine.gone_at.is_(None))
            .values(state=MachineState.GONE, gone_at=datetime.now(UTC), gone_reason=reason[:64]),
        )
        await session.commit()
    logger.info("pool machine %s gone: %s", name, reason)


async def machine(name: str) -> PoolMachine | None:
    async with SessionLocal() as session:
        return await session.scalar(select(PoolMachine).where(PoolMachine.name == name))


async def live() -> list[PoolMachine]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(PoolMachine)
            .where(PoolMachine.gone_at.is_(None))
            .order_by(PoolMachine.started_at),
        )
        return list(rows)


async def of_user(user_id: int) -> list[PoolMachine]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(PoolMachine)
            .where(
                PoolMachine.user_id == user_id,
                PoolMachine.gone_at.is_(None),
                PoolMachine.state == MachineState.LEASED,
            )
            .order_by(PoolMachine.leased_at),
        )
        return list(rows)


async def counted() -> dict[str, int]:
    machines = await live()
    counts: dict[str, int] = {"idle": 0, "leased": 0, "ci": 0, "booting": 0}
    for row in machines:
        counts[row.state] = counts.get(row.state, 0) + 1
    counts["total"] = len(machines)
    return counts


async def reap() -> int:
    if time.monotonic() - BOOTED < settings.pool_machine_ttl:
        return 0
    gone = 0
    for row in await live():
        if await alive(row.name):
            continue
        await forget(row.name, "no heartbeat")
        gone += 1
    return gone
