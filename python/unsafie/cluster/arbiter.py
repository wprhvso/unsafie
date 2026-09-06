import base64
import json
import logging

import aiohttp

from unsafie.settings import settings

logger = logging.getLogger(__name__)

GITHUB = "https://api.github.com"
TELEGRAM = "https://api.telegram.org"


async def read_cas() -> tuple[dict | None, str | None]:
    if not settings.arbiter_repo or not settings.arbiter_token:
        return None, None
    url = f"{GITHUB}/repos/{settings.arbiter_repo}/contents/{settings.arbiter_path}"
    headers = {"Authorization": f"Bearer {settings.arbiter_token}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers) as r:
            if r.status == 404:
                return {}, None
            if r.status != 200:
                logger.warning("arbiter read %s", r.status)
                return None, None
            data = await r.json()
    sha = data.get("sha")
    try:
        content = json.loads(base64.b64decode(data["content"]).decode())
    except (KeyError, ValueError):
        content = {}
    return content, sha


async def claim_cas(term: int, leader: str, reason: str, sha: str | None) -> bool:
    if not settings.arbiter_repo or not settings.arbiter_token:
        return False
    url = f"{GITHUB}/repos/{settings.arbiter_repo}/contents/{settings.arbiter_path}"
    headers = {"Authorization": f"Bearer {settings.arbiter_token}"}
    body = {
        "message": f"leader {leader} term {term}",
        "content": base64.b64encode(
            json.dumps({"term": term, "leader": leader, "reason": reason}).encode()
        ).decode(),
    }
    if sha:
        body["sha"] = sha
    async with aiohttp.ClientSession() as s:
        async with s.put(url, headers=headers, json=body) as r:
            if r.status in (200, 201):
                return True
            logger.info("arbiter claim rejected %s", r.status)
            return False


async def webhook_oracle() -> bool:
    if not settings.leader_bot_token:
        return False
    url = f"{TELEGRAM}/bot{settings.leader_bot_token}/getWebhookInfo"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = (await r.json()).get("result", {})
    except Exception as e:
        logger.warning("webhook oracle failed: %s", e)
        return False
    pending = data.get("pending_update_count", 0)
    last_error = data.get("last_error_date", 0)
    return pending > 0 or bool(last_error)
