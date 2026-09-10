"""A stop button for a turn, readable from any instance."""

import logging
from uuid import UUID

from unsafie import cluster
from unsafie.settings import settings

logger = logging.getLogger(__name__)

TTL = 3600.0


def key(turn_id: UUID) -> str:
    return cluster.key("cancel", str(turn_id))


async def ask(turn_id: UUID) -> None:
    """Mark the turn as unwanted: its own instance notices within a heartbeat."""
    ttl = int(max(TTL, settings.turn_stale_after * 2) * 1000)
    await cluster.client().set(key(turn_id), "1", px=ttl)
    logger.info("turn=%s asked to stop", turn_id)


async def asked(turn_id: UUID) -> bool:
    return bool(await cluster.client().get(key(turn_id)))


async def clear(turn_id: UUID) -> None:
    await cluster.client().delete(key(turn_id))
