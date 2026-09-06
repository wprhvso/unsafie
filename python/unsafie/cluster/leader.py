import asyncio
import logging

from unsafie.database import SessionLocal
from unsafie.database.models.cluster import ClusterState
from unsafie.settings import settings

logger = logging.getLogger(__name__)


async def _run(cmd: str) -> None:
    if not cmd:
        return
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    logger.info("leader cmd rc=%s: %s", proc.returncode, (out or b"").decode()[:500])


async def record(term: int, leader: str | None, reason: str, durable: bool) -> None:
    async with SessionLocal() as session:
        state = await session.get(ClusterState, 1)
        if state is None:
            state = ClusterState(id=1)
            session.add(state)
        state.term = term
        state.leader = leader
        state.reason = reason
        state.durable = durable
        await session.commit()


async def on_acquire(term: int, reason: str) -> None:
    logger.warning("becoming leader term=%s reason=%s", term, reason)
    await _run(settings.leader_promote_cmd)
    if settings.webhook_base_url and settings.leader_bot_token:
        await _set_webhook()
    await _run(settings.leader_dns_cmd)


async def on_release(term: int) -> None:
    logger.warning("stepping down from leadership term=%s", term)


async def _set_webhook() -> None:
    import aiohttp

    url = f"https://api.telegram.org/bot{settings.leader_bot_token}/setWebhook"
    hook = f"{settings.webhook_base_url.rstrip('/')}/tg/{settings.webhook_secret}"
    body = {"url": hook, "secret_token": settings.webhook_secret, "max_connections": 40}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as r:
                logger.info("setWebhook %s -> %s", hook, r.status)
    except Exception as e:
        logger.error("setWebhook failed: %s", e)
