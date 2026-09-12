import base64
import binascii
import json
from unsafie.log import get_logger
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any

import aiohttp

from unsafie.errors import OpsError
from unsafie.github.client.base import GithubHTTP, session
from unsafie.settings import settings

logger = get_logger(__name__)

API_VERSION = "6.0-preview"
CAPACITY_HEADER = "X-ScaleSetMaxCapacity"
RUNNER_GROUP = 1
RUNNER_PREFIX = "unsafie-"
AGENTS = "_apis/distributedtask/pools/0/agents"
SERVER = "https://github.com"
SKEW = 300.0
CALL_TIMEOUT = 45.0
POLL_TIMEOUT = 50.0
DEFAULT_LIFE = 600.0


class ScaleSetError(OpsError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Session:
    session_id: str
    queue_url: str
    queue_token: str
    queue_expiry: float
    statistics: dict

    @property
    def stale(self) -> bool:
        return time.time() > self.queue_expiry - SKEW


def _expiry(token: str) -> float:
    parts = token.split(".")
    if len(parts) < 2:
        return time.time() + DEFAULT_LIFE
    body = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return time.time() + DEFAULT_LIFE
    return float(payload.get("exp") or time.time() + DEFAULT_LIFE)


def _versioned(url: str) -> str:
    return url + ("&" if "?" in url else "?") + f"api-version={API_VERSION}"


class ScaleSet:
    def __init__(self, slug: str, token: str, work: str = "_work") -> None:
        self.slug = slug
        self.token = token
        self.work = work
        self._jwt = ""
        self._jwt_expiry = 0.0
        self._pipeline = ""

    async def registration_token(self) -> str:
        answer = await GithubHTTP(self.token).request(
            "POST", f"/repos/{self.slug}/actions/runners/registration-token",
        )
        value = str((answer or {}).get("token") or "")
        if not value:
            msg = f"{self.slug}: github gave no registration token"
            raise ScaleSetError(msg)
        return value

    async def _authenticate(self, force: bool = False) -> None:
        if not force and self._jwt and time.time() < self._jwt_expiry - SKEW:
            return
        info = await self._raw(
            "POST",
            f"{settings.github_api_url}/actions/runner-registration",
            auth=f"RemoteAuth {await self.registration_token()}",
            body={"url": f"{SERVER}/{self.slug}", "runner_event": "register"},
        )
        if not isinstance(info, dict) or not info.get("token") or not info.get("url"):
            msg = f"{self.slug}: runner-registration answered without a token"
            raise ScaleSetError(msg)
        self._jwt = str(info["token"])
        self._jwt_expiry = _expiry(self._jwt)
        self._pipeline = str(info["url"]).rstrip("/")

    async def _raw(
        self,
        method: str,
        url: str,
        *,
        auth: str,
        body: Any = None,
        timeout: float = CALL_TIMEOUT,
        extra: dict[str, str] | None = None,
    ) -> Any:
        headers = {
            "Accept": f"application/json; api-version={API_VERSION}",
            "Content-Type": "application/json",
            "User-Agent": "unsafie",
            "Authorization": auth,
        }
        if extra:
            headers.update(extra)
        http = await session()
        async with http.request(
            method,
            url,
            headers=headers,
            json=body,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as answer:
            raw = await answer.read()
            if answer.status >= 400:
                head = raw[:300].decode(errors="replace")
                msg = f"{method} {url.split('?', maxsplit=1)[0]} -> {answer.status}: {head}"
                raise ScaleSetError(
                    msg, answer.status,
                )
            if not raw:
                return None
            try:
                return json.loads(raw)
            except ValueError:
                return None

    async def call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        auth: str | None = None,
        relative: bool = True,
        timeout: float = CALL_TIMEOUT,
        extra: dict[str, str] | None = None,
    ) -> Any:
        await self._authenticate()
        base = f"{self._pipeline}/_apis/runtime/{path}" if relative else f"{self._pipeline}/{path}"
        url = _versioned(base)
        if auth is not None:
            return await self._raw(method, url, auth=auth, body=body, timeout=timeout, extra=extra)
        try:
            return await self._raw(
                method, url, auth=f"Bearer {self._jwt}", body=body, timeout=timeout, extra=extra,
            )
        except ScaleSetError as refused:
            if refused.status != 401:
                raise
            await self._authenticate(force=True)
            return await self._raw(
                method, url, auth=f"Bearer {self._jwt}", body=body, timeout=timeout, extra=extra,
            )

    async def find(self, name: str) -> dict | None:
        query = urllib.parse.quote(name, safe="")
        try:
            found = await self.call("GET", f"runnerscalesets?name={query}")
        except ScaleSetError as refused:
            if refused.status == 404:
                return None
            raise
        values = found.get("value", []) if isinstance(found, dict) else (found or [])
        for item in values:
            if isinstance(item, dict) and item.get("name") == name:
                return item
        return None

    async def ensure(self, name: str) -> dict:
        existing = await self.find(name)
        if existing:
            return existing
        created = await self.call(
            "POST",
            "runnerscalesets",
            body={
                "name": name,
                "runnerGroupId": RUNNER_GROUP,
                "labels": [{"name": name, "type": "System"}],
                "runnerSetting": {"ephemeral": True, "disableUpdate": True},
            },
        )
        if not isinstance(created, dict) or "id" not in created:
            msg = f"{self.slug}: could not create the scale set '{name}'"
            raise ScaleSetError(msg)
        logger.info("pool ci %s: scale set %s created id=%s", self.slug, name, created["id"])
        return created

    async def drop(self, scale_set_id: int) -> None:
        try:
            await self.call("DELETE", f"runnerscalesets/{scale_set_id}")
        except ScaleSetError as refused:
            if refused.status != 404:
                raise

    async def statistics(self, scale_set_id: int) -> dict:
        answer = await self.call("GET", f"runnerscalesets/{scale_set_id}")
        stats = (answer or {}).get("statistics") if isinstance(answer, dict) else None
        return stats if isinstance(stats, dict) else {}

    async def jit(self, scale_set_id: int) -> tuple[int, str, str]:
        name = f"{RUNNER_PREFIX}{uuid.uuid4().hex[:12]}"
        answer = await self.call(
            "POST",
            f"runnerscalesets/{scale_set_id}/generatejitconfig",
            body={"name": name, "workFolder": self.work},
        )
        payload = answer if isinstance(answer, dict) else {}
        config = str(payload.get("encodedJITConfig") or "")
        if not config:
            msg = f"{self.slug}: empty jit config"
            raise ScaleSetError(msg)
        runner = payload.get("runner")
        runner_id = int(runner.get("id") or 0) if isinstance(runner, dict) else 0
        return runner_id, name, config

    async def forget(self, runner_id: int) -> bool:
        if not runner_id:
            return False
        try:
            await self.call("DELETE", f"{AGENTS}/{runner_id}", relative=False)
        except ScaleSetError as refused:
            logger.debug("pool ci %s: runner %s stayed: %s", self.slug, runner_id, refused)
            return False
        return True

    @staticmethod
    def _session(raw: Any) -> Session:
        needed = ("sessionId", "messageQueueUrl", "messageQueueAccessToken")
        if not isinstance(raw, dict) or any(key not in raw for key in needed):
            msg = "the answer carries no message session"
            raise ScaleSetError(msg)
        token = str(raw["messageQueueAccessToken"])
        statistics = raw.get("statistics")
        return Session(
            session_id=str(raw["sessionId"]),
            queue_url=str(raw["messageQueueUrl"]),
            queue_token=token,
            queue_expiry=_expiry(token),
            statistics=statistics if isinstance(statistics, dict) else {},
        )

    async def open(self, scale_set_id: int, owner: str) -> Session:
        opened = self._session(
            await self.call(
                "POST", f"runnerscalesets/{scale_set_id}/sessions", body={"ownerName": owner},
            ),
        )
        logger.info("pool ci %s: message session %s open", self.slug, opened.session_id)
        return opened

    async def refresh(self, scale_set_id: int, current: Session) -> Session:
        return self._session(
            await self.call(
                "PATCH", f"runnerscalesets/{scale_set_id}/sessions/{current.session_id}",
            ),
        )

    async def close(
        self, scale_set_id: int, current: Session, timeout: float = 2.0,
    ) -> None:
        try:
            await self.call(
                "DELETE",
                f"runnerscalesets/{scale_set_id}/sessions/{current.session_id}",
                timeout=timeout,
            )
        except ScaleSetError as refused:
            if refused.status != 404:
                raise

    async def poll(self, current: Session, last_message_id: int, capacity: int) -> dict | None:
        url = current.queue_url
        if last_message_id > 0:
            url += ("&" if "?" in url else "?") + f"lastMessageId={last_message_id}"
        try:
            message = await self._raw(
                "GET",
                url,
                auth=f"Bearer {current.queue_token}",
                timeout=POLL_TIMEOUT + 15.0,
                extra={CAPACITY_HEADER: str(max(0, capacity))},
            )
        except TimeoutError:
            return None
        return message if isinstance(message, dict) else None

    async def ack(self, current: Session, message_id: int) -> None:
        base, _, query = current.queue_url.partition("?")
        url = f"{base}/{message_id}?{query}" if query else f"{base}/{message_id}"
        try:
            await self._raw("DELETE", url, auth=f"Bearer {current.queue_token}")
        except ScaleSetError as refused:
            if refused.status not in (404, 410):
                raise

    async def acquire(self, scale_set_id: int, current: Session, request_ids: list[int]) -> int:
        if not request_ids:
            return 0
        answer = await self.call(
            "POST",
            f"runnerscalesets/{scale_set_id}/acquirejobs",
            body=request_ids,
            auth=f"Bearer {current.queue_token}",
        )
        taken = answer.get("value", []) if isinstance(answer, dict) else (answer or [])
        return len(taken) if isinstance(taken, list) else 0
