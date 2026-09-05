import logging

from unsafie import events
from unsafie.database import SessionLocal
from unsafie.database.repositories.delivery import DeliveryRepository

logger = logging.getLogger(__name__)


def summarize(event: str, payload: dict) -> dict:
    repo = (payload.get("repository") or {}).get("full_name")
    return {
        "action": payload.get("action"),
        "installation_id": (payload.get("installation") or {}).get("id"),
        "repo_full_name": repo,
        "sender": (payload.get("sender") or {}).get("login"),
    }


async def accept(delivery_id: str, event: str, payload: dict) -> bool:
    meta = summarize(event, payload)
    async with SessionLocal() as session:
        fresh = await DeliveryRepository(session).store(
            delivery_id=delivery_id, event=event, payload=payload, **meta
        )
    if not fresh:
        logger.info("delivery=%s %s already seen", delivery_id, event)
        return False
    events.publish(
        "webhook.received",
        delivery_id=delivery_id,
        event=event,
        action=meta["action"],
        repo=meta["repo_full_name"],
        sender=meta["sender"],
    )
    return True


async def done(delivery_id: str, notified: int, error: str | None) -> None:
    async with SessionLocal() as session:
        await DeliveryRepository(session).processed(delivery_id, notified, error)
    events.publish("webhook.processed", delivery_id=delivery_id, notified=notified, error=error)
