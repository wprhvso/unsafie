import json
import os
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API = "http://127.0.0.1:8000"
TIMEOUT = 120.0
USER_AGENT = "unsafie-cli"
KEYS = ("token", "api", "chat")
ENV = {
    "token": "UNSAFIE_TOKEN",
    "api": "UNSAFIE_API",
    "chat": "UNSAFIE_CHAT",
}


class CliError(Exception):
    pass


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
    found = os.environ.get(ENV.get(key, ""))
    if found:
        return found
    stored = _file().get(key)
    if stored:
        return stored
    return DEFAULT_API if key == "api" else None


class Client:
    def __init__(self, api: str | None = None, token: str | None = None, prefix: str = "/api/v1"):
        self.api = (setting("api", api) or DEFAULT_API).rstrip("/")
        self._token = token
        self.prefix = prefix

    @property
    def token(self) -> str:
        found = setting("token", self._token)
        if not found:
            raise CliError("no token provided: set UNSAFIE_TOKEN")
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
            err_body = refused.read()
            try:
                parsed = json.loads(err_body)
                detail = parsed.get("detail", str(parsed))
            except Exception:
                detail = err_body.decode(errors="replace") or str(refused)
            raise CliError(f"{refused.code}: {detail}") from None
        except Exception as e:
            raise CliError(str(e)) from None
        if raw:
            return data
        if not data:
            return None
        try:
            return json.loads(data)
        except ValueError:
            return data.decode(errors="replace")

    def upload(self, path: str, data: bytes, timeout: float = TIMEOUT) -> Any:
        url = f"{self.api}{self.prefix}{path}"
        request = urllib.request.Request(url, data=data, method="PUT")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                body = answer.read()
        except urllib.error.HTTPError as refused:
            raise CliError(f"{refused.code}: {refused.read().decode(errors='replace')}") from None
        except Exception as e:
            raise CliError(str(e)) from None
        return json.loads(body) if body else None


_shared: Client | None = None


def client() -> Client:
    global _shared
    if _shared is None:
        _shared = Client()
    return _shared
