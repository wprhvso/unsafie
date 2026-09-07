import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from unsafie_cli import config
from unsafie_cli.errors import LIMIT, NOT_FOUND, CliError, NoAuth
from unsafie_cli.parser import Call

TIMEOUT = 120.0
USER_AGENT = "unsafie-cli"


class Api:
    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float = TIMEOUT,
    ) -> Any:
        url = f"{self.base}/api/v1{path}"
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "", False)}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(url, data=payload, method=method.upper())
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", USER_AGENT)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                raw = answer.read()
        except urllib.error.HTTPError as refused:
            raise _refusal(refused) from None
        except urllib.error.URLError as unreachable:
            raise CliError(
                f"{self.base} is not answering: {unreachable.reason}",
                hint="check `unsafie config get api`, or the server is down",
            ) from None
        except TimeoutError:
            raise CliError(f"{self.base} did not answer in {timeout:.0f}s") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode(errors="replace")


    def raw(self, method: str, path: str, data: bytes, timeout: float = TIMEOUT) -> Any:
        request = urllib.request.Request(
            f"{self.base}/api/v1{path}", data=data, method=method.upper()
        )
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                body = answer.read()
        except urllib.error.HTTPError as refused:
            raise _refusal(refused) from None
        except urllib.error.URLError as unreachable:
            raise CliError(f"{self.base} is not answering: {unreachable.reason}") from None
        return json.loads(body) if body else None

    def download(self, path: str, timeout: float = TIMEOUT) -> bytes:
        request = urllib.request.Request(f"{self.base}/api/v1{path}", method="GET")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                return answer.read()
        except urllib.error.HTTPError as refused:
            raise _refusal(refused) from None
        except urllib.error.URLError as unreachable:
            raise CliError(f"{self.base} is not answering: {unreachable.reason}") from None


def _refusal(error: urllib.error.HTTPError) -> CliError:
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
        return NoAuth(message, "unsafie auth status shows which token is in play")
    if error.code == 404:
        return CliError(message, NOT_FOUND)
    if error.code in (409, 429):
        return CliError(message, LIMIT)
    return CliError(f"{error.code}: {message}")


def client(call: Call) -> Api:
    token = config.resolve("token", call.options.token)
    if token is None:
        raise NoAuth()
    base = config.resolve("api", call.options.api)
    return Api(base.value if base else config.DEFAULT_API, token.value)


def chat_of(call: Call) -> int | None:
    found = config.resolve("chat", call.options.chat)
    if found is None:
        return None
    try:
        return int(found.value)
    except ValueError:
        return None


def turn_of() -> str | None:
    import os

    return os.environ.get("UNSAFIE_TURN") or None
