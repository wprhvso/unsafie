from uuid import UUID

from unsafie import cluster
from unsafie.settings import settings

INJECT_HEADER = (
    "While you were working, the user sent new messages (JSON, one per line). "
    "Take them into account as soon as possible: adjust the current task if they change it, "
    "and reply to them via send_message."
)

DRAIN = """
local items = redis.call('lrange', KEYS[1], 0, -1)
redis.call('del', KEYS[1])
return items
"""


def key(turn_id: UUID) -> str:
    return cluster.key("inject", turn_id)


async def enqueue(turn_id: UUID, prompt: str) -> int:
    client = cluster.client()
    name = key(turn_id)
    pipe = client.pipeline(transaction=True)
    pipe.rpush(name, prompt)
    pipe.pexpire(name, int(settings.queue_ttl * 1000))
    length, _ = await pipe.execute()
    return int(length)


async def drain(turn_id: UUID) -> str | None:
    items = await cluster.client().eval(DRAIN, 1, key(turn_id))
    if not items:
        return None
    return INJECT_HEADER + "\n\n" + "\n".join(items)


async def clear(turn_id: UUID) -> None:
    await cluster.client().delete(key(turn_id))
