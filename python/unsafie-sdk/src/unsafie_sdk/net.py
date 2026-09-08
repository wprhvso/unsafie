import importlib
import json
import re
import urllib.error
import urllib.request
from typing import Any

from unsafie_sdk.errors import UnsafieError

LIMIT = 8_000_000
AGENT = "unsafie-sdk"


def _converter():
    for module, attribute in (("bloat2md", "to_markdown"), ("llmmd", "html_to_markdown")):
        try:
            found = getattr(importlib.import_module(module), attribute, None)
        except ImportError:
            continue
        if callable(found):
            return found
    return None


def to_markdown(html: str) -> str:
    """Turn html into markdown, with a plain-text fallback when no converter is installed."""
    convert = _converter()
    if convert is not None:
        try:
            return str(convert(html))
        except Exception:
            pass
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return re.sub(r"[ \t]*\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", body)).strip()


def fetch(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30.0) -> str:
    """Fetch a page and return it as markdown (json comes back pretty-printed)."""
    body, kind = _get(url, headers, timeout)
    if "json" in kind:
        try:
            return json.dumps(json.loads(body), ensure_ascii=False, indent=1)
        except ValueError:
            return body
    if "html" in kind:
        return to_markdown(body)
    return body


def get_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30.0) -> Any:
    """Fetch a url and parse it as json."""
    body, _ = _get(url, headers, timeout)
    try:
        return json.loads(body)
    except ValueError:
        raise UnsafieError(f"{url} did not answer with json") from None


def _get(url: str, headers: dict[str, str] | None, timeout: float) -> tuple[str, str]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return answer.read(LIMIT).decode(errors="replace"), answer.headers.get_content_type()
    except urllib.error.HTTPError as refused:
        raise UnsafieError(f"{url} answered {refused.code}") from None
    except (urllib.error.URLError, TimeoutError) as unreachable:
        raise UnsafieError(f"{url} is not answering: {unreachable}") from None
