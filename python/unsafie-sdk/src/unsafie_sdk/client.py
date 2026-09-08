import json
import os
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from unsafie_sdk.errors import LimitReached, NotAuthorized, NotFound, Refused, UnsafieError

DEFAULT_API = "https://unsafie.com"
TIMEOUT = 120.0
USER_AGENT = "unsafie-sdk"
KEYS = ("token", "api", "chat", "machine")
ENV = {
    "token": "UNSAFIE_TOKEN",
    "api": "UNSAFIE_API",
    "chat": "UNSAFIE_CHAT",
    "machine": "UNSAFIE_MACHINE",
}


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "unsafie" / "config.toml"


def _file() -> dict[str, str]:
    target = config_path()
    if not target.is_file():
        return {}
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {key: str(value) for key, value in raw.items() if key in KEYS}


def setting(key: str, override: str | None = None) -> str | None:
    if override:
        return override
    found = os.environ.get(ENV[key])
    if found:
        return found
    stored = _file().get(key)
    if stored:
        return stored
    return DEFAULT_API if key == "api" else None


def save(values: dict[str, str]) -> Path:
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f'{key} = "{values[key]}"\n' for key in KEYS if values.get(key))
    target.write_text(body, encoding="utf-8")
    target.chmod(0o600)
    return target


class Client:
    def __init__(self, api: str | None = None, token: str | None = None, prefix: str = "/api/v1"):
        self.api = (setting("api", api) or DEFAULT_API).rstrip("/")
        self._token = token
        self.prefix = prefix

    @property
    def token(self) -> str:
        found = setting("token", self._token)
        if not found:
            raise NotAuthorized(
                "no token",
                "on a machine it arrives in UNSAFIE_TOKEN; a human gets one with /auth in Telegram",
            )
        return found

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float = TIMEOUT,
        raw: bool = False,
    ) -> Any:
        url = f"{self.api}{self.prefix}{path}"
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"
        payload = None if body is None else json.dumps(body, ensure_ascii=False, default=str).encode()
        request = urllib.request.Request(url, data=payload, method=method.upper())
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", USER_AGENT)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                data = answer.read()
        except urllib.error.HTTPError as refused:
            raise _refusal(refused) from None
        except urllib.error.URLError as unreachable:
            raise UnsafieError(f"{self.api} is not answering: {unreachable.reason}") from None
        except TimeoutError:
            raise UnsafieError(f"{self.api} did not answer in {timeout:.0f}s") from None
        if raw:
            return data
        if not data:
            return None
        try:
            return json.loads(data)
        except ValueError:
            return data.decode(errors="replace")

    def upload(self, path: str, data: bytes, timeout: float = TIMEOUT) -> Any:
        request = urllib.request.Request(f"{self.api}{self.prefix}{path}", data=data, method="PUT")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                body = answer.read()
        except urllib.error.HTTPError as refused:
            raise _refusal(refused) from None
        return json.loads(body) if body else None


def _refusal(error: urllib.error.HTTPError) -> UnsafieError:
    try:
        parsed = json.loads(error.read() or b"{}")
    except ValueError:
        parsed = None
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    if isinstance(detail, list):
        message = "; ".join(
            str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail
        )
    else:
        message = str(detail or error.reason or "refused")
    if error.code in (401, 403):
        return NotAuthorized(message)
    if error.code == 404:
        return NotFound(message)
    if error.code in (409, 429):
        return LimitReached(message)
    return Refused(f"{error.code}: {message}")


_shared: Client | None = None


def client() -> Client:
    global _shared
    if _shared is None:
        _shared = Client()
    return _shared

