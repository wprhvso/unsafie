import json
import logging
import time
from urllib.parse import urlparse

import aiohttp

from unsafie.agent.tools.base import ToolContext, error, schema, text
from unsafie.agent.tools.files import deliver
from unsafie.agent.tools.registry import register
from unsafie.mime import decode_text, human_size, sniff_mime
from unsafie.settings import settings

logger = logging.getLogger(__name__)

SERVER = "http"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
BODY_LIMIT = 60_000
SHOW_HEADERS = (
    "content-type",
    "content-length",
    "location",
    "server",
    "date",
    "cache-control",
    "x-request-id",
    "retry-after",
    "www-authenticate",
    "set-cookie",
    "etag",
    "last-modified",
)


def _headers(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"headers is not a JSON object: {e}") from None
    if not isinstance(data, dict):
        raise ValueError('headers must be a JSON object {"Name": "value"}')
    return {str(k): str(v) for k, v in data.items()}


def _pretty(data: bytes, ctype: str) -> tuple[str, str]:
    decoded = decode_text(data)
    if decoded is None:
        return (
            f"<binary {sniff_mime(data)} {human_size(len(data))}; use http_download to get it as a file>",
            "binary",
        )
    body = decoded[0]
    if "json" in ctype or body[:1] in ("{", "["):
        try:
            return json.dumps(json.loads(body), ensure_ascii=False, indent=1), "json"
        except ValueError:
            pass
    return body, "text"


async def _request(args: dict) -> tuple[int, dict, bytes, str, float]:
    method = (args.get("method") or "GET").strip().upper()
    if method not in METHODS:
        raise ValueError("method must be one of " + " | ".join(METHODS))
    url = (args.get("url") or "").strip()
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("an http(s) URL is required")
    headers = _headers(args.get("headers"))
    body = args.get("body")
    kwargs: dict = {}
    if body is not None and method not in ("GET", "HEAD"):
        if args.get("json", True) and body.strip()[:1] in ("{", "["):
            try:
                kwargs["json"] = json.loads(body)
            except ValueError:
                kwargs["data"] = body.encode()
        else:
            kwargs["data"] = body.encode()
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    timeout = max(
        1, min(int(args.get("timeout") or settings.http_timeout), settings.http_max_timeout)
    )
    limit = settings.http_max_body
    started = time.perf_counter()
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout), headers={"User-Agent": "unsafie"}
    ) as session:
        async with session.request(
            method,
            url,
            headers=headers,
            allow_redirects=args.get("follow_redirects", True),
            **kwargs,
        ) as r:
            buf = bytearray()
            async for chunk in r.content.iter_chunked(64 * 1024):
                buf.extend(chunk)
                if len(buf) > limit:
                    raise ValueError(
                        f"response exceeds {human_size(limit)}; use http_download or a Range header"
                    )
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            resp_headers = {k: v for k, v in r.headers.items() if k.lower() in SHOW_HEADERS}
            return r.status, resp_headers, bytes(buf), ctype, (time.perf_counter() - started) * 1000


@register(
    SERVER,
    "http_request",
    "Raw HTTP request: method (GET by default), url, headers as a JSON object, body as a string "
    "(sent as application/json when json=true and it looks like JSON), timeout in seconds. "
    "Returns status, key headers and the body: JSON pretty-printed, text as is (truncated), "
    "binary described. Prefer WebFetch for reading pages; this is for APIs, health endpoints, webhooks.",
    schema(
        ["url"],
        url=str,
        method=str,
        headers=str,
        body=str,
        json=bool,
        timeout=int,
        follow_redirects=bool,
    ),
)
async def http_request(ctx: ToolContext, args: dict) -> dict:
    try:
        status, headers, data, ctype, ms = await _request(args)
    except ValueError as e:
        return error(str(e))
    except TimeoutError:
        return error("timeout")
    except aiohttp.ClientError as e:
        return error(f"network error: {e}")
    body, _ = _pretty(data, ctype)
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + f"\n…(truncated, total {human_size(len(data))})"
    head = f"HTTP {status} {(args.get('method') or 'GET').upper()} {args['url'].strip()} ({human_size(len(data))}, {ms:.0f}ms)"
    hdrs = "\n".join(f"{k}: {v}" for k, v in headers.items())
    return text(f"{head}\n{hdrs}\n\n{body or '<empty body>'}")


@register(
    SERVER,
    "http_download",
    "Download a file by URL and send it to the user in the chat as is. headers is a JSON object "
    "(e.g. Authorization), filename is the name shown in the chat.",
    schema(["url"], url=str, headers=str, filename=str, caption=str, as_photo=bool),
    replies=True,
)
async def http_download(ctx: ToolContext, args: dict) -> dict:
    try:
        status, _, data, _, _ = await _request({**args, "method": "GET"})
    except ValueError as e:
        return error(str(e))
    except TimeoutError:
        return error("timeout")
    except aiohttp.ClientError as e:
        return error(f"network error: {e}")
    if status >= 400:
        return error(f"HTTP {status}")
    url = args["url"].strip()
    name = (
        (args.get("filename") or "").strip()
        or urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        or "file"
    )
    return await deliver(
        ctx, data, name, caption=args.get("caption"), as_photo=bool(args.get("as_photo"))
    )
