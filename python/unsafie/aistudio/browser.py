from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import random
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, TypeVar

import aiohttp
from pycdp.cdp import emulation, fetch, input_, network, page, runtime, target

from unsafie.log import get_logger
from unsafie.settings import settings

from .formatter import clean_model_response
from .mouse import HumanMouse

if TYPE_CHECKING:
    from collections.abc import Generator

logger = get_logger(__name__)
T = TypeVar("T")


class RateLimitError(RuntimeError):
    pass


class UnusableProfileError(RuntimeError):
    pass


def _is_thought_part(node: Any) -> bool:
    if isinstance(node, dict):
        return bool(node.get("thought"))
    if isinstance(node, list):
        for idx in (10, 11, 12, 13):
            if len(node) > idx and node[idx] in (1, True, "1"):
                return True
    return False


def extract_gemini_text(raw_data: Any) -> str:
    # 1. Если пришла строка (SSE стрим или сырой JSON)
    if isinstance(raw_data, str):
        text = raw_data.strip()
        if text.startswith(")]}'"):
            text = text[4:].strip()
        try:
            raw_data = json.loads(text)
        except Exception:
            lines = [line for line in text.splitlines() if line.strip()]
            parts: list[str] = []
            for line in lines:
                l = line.strip()
                if l.startswith("data:"):
                    l = l[5:].strip()
                if l.startswith(")]}'"):
                    l = l[4:].strip()
                try:
                    parsed = json.loads(l)
                    sub = extract_gemini_text(parsed)
                    if sub:
                        parts.append(sub)
                except Exception:
                    pass
            return "".join(parts)

    # 2. Если пришел стандартный dict (Gemini API v1/v1beta)
    if isinstance(raw_data, dict):
        if raw_data.get("candidates"):
            cand = raw_data["candidates"][0]
            parts = cand.get("content", {}).get("parts", [])
            text_parts = [
                p.get("text", "")
                for p in parts
                if isinstance(p, dict) and "text" in p and not p.get("thought")
            ]
            if text_parts:
                return "".join(text_parts)
        if "error" in raw_data:
            err = raw_data["error"]
            code = err.get("code") or err.get("status")
            msg = err.get("message", "Error")
            if code == 429 or "RESOURCE_EXHAUSTED" in str(code):
                raise RateLimitError(f"Google AI Studio rate limit (429): {msg}")
            raise RuntimeError(f"API Error {code}: {msg}")
        return ""

    # 3. Protobuf-over-JSON массив Google AI Studio (Alkali)
    if isinstance(raw_data, list):
        chunks = raw_data

        # Снимаем внешние списки-обертки, пока не дойдем до списка чанков
        while (
            isinstance(chunks, list)
            and len(chunks) == 1
            and isinstance(chunks[0], list)
            and not (len(chunks[0]) >= 2 and chunks[0][1] is None)
        ):
            chunks = chunks[0]

        collected_texts: list[str] = []

        for item in chunks:
            if not isinstance(item, list) or not item:
                continue

            # Спускаемся строго до Content: [parts_list, "model"]
            curr = item[0]
            content_parts = None

            while isinstance(curr, list) and curr:
                # Content в Alkali: [parts, "model"]
                if len(curr) >= 2 and curr[1] == "model" and isinstance(curr[0], list):
                    content_parts = curr[0]
                    break
                if isinstance(curr[0], list):
                    curr = curr[0]
                else:
                    break

            if not content_parts:
                continue

            for part in content_parts:
                # Обработка Part (массив protobuf)
                if isinstance(part, list):
                    if len(part) < 2:
                        continue
                    # Индекс 12 в Part — флаг thought (1 / True)
                    if len(part) > 12 and part[12] in (1, True, "1"):
                        continue
                    # Читаем СТРОГО индекс 1 (поле text). Индекс 14 с токеном игнорируется.
                    text_val = part[1]
                    if isinstance(text_val, str) and text_val:
                        collected_texts.append(text_val)

                # Обработка Part (если внутри оказался dict)
                elif isinstance(part, dict):
                    if part.get("thought"):
                        continue
                    text_val = part.get("text")
                    if isinstance(text_val, str) and text_val:
                        collected_texts.append(text_val)

        return "".join(collected_texts)

    return ""


def _clear_chromium_singleton_locks() -> None:
    with contextlib.suppress(Exception):
        subprocess.run(
            [
                "docker",
                "exec",
                "kameleo",
                "sh",
                "-c",
                "find / -name 'Singleton*' -delete 2>/dev/null",
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
    with contextlib.suppress(Exception):
        for p in Path("/var/lib/docker/volumes/kameleo-data").rglob("Singleton*"):
            with contextlib.suppress(Exception):
                p.unlink()


def _format_screenshot_path(profile_id: str, reason: str = "") -> Path:
    ts = int(time.time())
    iso = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    clean_reason = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in reason)
    pattern = getattr(
        settings,
        "aistudio_screenshot_pattern",
        "/var/lib/unsafie/screenshots/aistudio_error_{profile_id}_{timestamp}.png",
    )
    try:
        resolved = pattern.format(
            profile_id=profile_id,
            timestamp=ts,
            time=iso,
            reason=clean_reason,
        )
    except Exception:
        resolved = f"/var/lib/unsafie/screenshots/aistudio_error_{profile_id}_{ts}.png"
    p = Path(resolved)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        p = Path(f"/tmp/aistudio_error_{profile_id}_{ts}.png")
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _start_profile_headless(endpoint: str, profile_id: str) -> None:
    from kameleo.local_api_client.kameleo_local_api_client import KameleoLocalApiClient
    import kameleo.local_api_client.models as k_models

    _clear_chromium_singleton_locks()
    logger.info("kameleo.profile.start.request", endpoint=endpoint, profile_id=profile_id)
    client = KameleoLocalApiClient(endpoint=endpoint)
    try:
        client.profile.stop_profile(profile_id)
    except Exception:
        pass

    req_cls = getattr(k_models, "BrowserStartRequest", None) or getattr(
        k_models, "StartProfileRequest", None
    )

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            if req_cls:
                req = req_cls(headless=True)
                if hasattr(client.profile, "start_profile_with_options"):
                    client.profile.start_profile_with_options(profile_id, req)
                    logger.info("kameleo.profile.start.options_done", profile_id=profile_id)
                    return
                if hasattr(client.profile, "start_profile"):
                    try:
                        client.profile.start_profile(profile_id, body=req)
                        logger.info("kameleo.profile.start.body_done", profile_id=profile_id)
                        return
                    except TypeError:
                        client.profile.start_profile(profile_id, req)
                        logger.info("kameleo.profile.start.req_done", profile_id=profile_id)
                        return

            if hasattr(client.profile, "start_profile"):
                client.profile.start_profile(profile_id)
                logger.info("kameleo.profile.start.plain_done", profile_id=profile_id)
                return
        except Exception as e:
            last_error = e
            logger.warning(
                "kameleo.profile.start.retry_needed",
                profile_id=profile_id,
                attempt=attempt + 1,
                error=str(e),
            )
            _clear_chromium_singleton_locks()
            try:
                client.profile.stop_profile(profile_id)
            except Exception:
                pass
            time.sleep(1.0)

    if last_error is not None:
        raise last_error


def _build_alkali_resource(prompt_id: str, prompt_text: str) -> list[Any]:
    now = time.time()
    seconds = str(int(now))
    nanoseconds = int((now % 1) * 1_000_000_000)

    user_item: list[Any] = [None for _ in range(37)]
    user_item[0] = prompt_text
    user_item[8] = "user"
    user_item[18] = None
    user_item[28] = ""
    user_item[30] = 0
    user_item[31] = 0
    user_item[32] = None
    user_item[35] = ""
    user_item[36] = ""

    cfg: list[Any] = [None for _ in range(48)]
    cfg[0] = 1.0
    cfg[2] = "models/gemini-3.8-flash"
    cfg[4] = 0.95
    cfg[5] = 64
    cfg[6] = 65536
    cfg[7] = [
        [None, None, 7, 5],
        [None, None, 8, 5],
        [None, None, 9, 5],
        [None, None, 10, 5],
    ]
    cfg[9] = 0
    cfg[14] = 0
    cfg[17] = 0
    cfg[24] = -1
    cfg[28] = 3
    for idx in (30, 31, 32, 33, 34, 41, 42, 47):
        cfg[idx] = 0

    meta: list[Any] = [
        "Greeting And Offering Assistance",
        None,
        ["User", 1, ""],
        None,
        [[seconds, nanoseconds], ["User", 1, ""]],
        [1, 1, 1],
        None,
        None,
        None,
        None,
        [],
        [
            ["hasImages", "false"],
            ["version", "1"],
            ["promptType", "CHUNKED_PROMPT"],
        ],
    ]

    payload: list[Any] = [None for _ in range(14)]
    payload[0] = f"prompts/{prompt_id}"
    payload[3] = cfg
    payload[4] = meta
    payload[12] = []
    payload[13] = [
        [],
        [user_item],
    ]

    return [payload]


class AistudioBrowser:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        profile: dict[str, Any],
        endpoint: str = "http://localhost:5050",
    ) -> None:
        self.session = session
        self.profile = profile
        self.endpoint = endpoint
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._cmd_counter: int = 0
        self._pending_cmds: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._current_session_id: str | None = None
        self._current_target_id: str | None = None
        self._active_mock_body: str | None = None
        self._signature_future: asyncio.Future[dict[str, Any]] | None = None
        self.mouse = HumanMouse(browser=self)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def dump_ui_state(self) -> dict[str, Any]:
        js = """
        (() => {
            const alerts = Array.from(document.querySelectorAll('[role="alert"], mat-snack-bar-container, .error-message, .ms-error'))
                .map(el => (el.innerText || '').trim()).filter(Boolean);
            const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
                .map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean);
            return {
                url: window.location.href,
                alerts: alerts,
                buttons: buttons.slice(0, 20),
                bodyPreview: document.body ? document.body.innerText.slice(0, 400).replace(/\\n+/g, ' ') : ''
            };
        })()
        """
        try:
            res, _ = await self.execute(runtime.evaluate(expression=js, return_by_value=True))
            return res.value if res and isinstance(res.value, dict) else {}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_fetch_event(self, params: dict[str, Any]) -> None:
        req_id = params.get("requestId")
        req = params.get("request", {})
        url = req.get("url", "")
        method = req.get("method", "").upper()

        logger.info(
            "aistudio.fetch.intercepted",
            method=method,
            url=url[:150],
            req_id=req_id,
        )

        if method == "OPTIONS":
            req_headers = req.get("headers", {})
            requested_headers = (
                req_headers.get("access-control-request-headers")
                or req_headers.get("Access-Control-Request-Headers")
                or "Content-Type, Authorization, X-Goog-Api-Client, X-User-Agent, X-Origin"
            )
            origin = (
                req_headers.get("origin")
                or req_headers.get("Origin")
                or "https://aistudio.google.com"
            )
            logger.info(
                "aistudio.fetch.preflight_options_fixed", requested_headers=requested_headers
            )
            await self.execute(
                fetch.fulfill_request(
                    request_id=fetch.RequestId(str(req_id)),
                    response_code=200,
                    response_headers=[
                        fetch.HeaderEntry(name="Access-Control-Allow-Origin", value=origin),
                        fetch.HeaderEntry(
                            name="Access-Control-Allow-Methods", value="GET, POST, OPTIONS"
                        ),
                        fetch.HeaderEntry(
                            name="Access-Control-Allow-Headers", value=requested_headers
                        ),
                        fetch.HeaderEntry(name="Access-Control-Allow-Credentials", value="true"),
                        fetch.HeaderEntry(name="Access-Control-Max-Age", value="86400"),
                    ],
                )
            )
            return

        if "ResolveDriveResource" in url:
            post_data = req.get("postData", "")
            logger.info(
                "aistudio.fetch.resolve_drive_detected",
                url=url,
                method=method,
                has_active_mock=bool(self._active_mock_body),
                incoming_payload=post_data[:300] if post_data else "",
            )
            if self._active_mock_body:
                b64_body = base64.b64encode(self._active_mock_body.encode("utf-8")).decode("utf-8")
                logger.info(
                    "aistudio.fetch.fulfilling_mock",
                    body_len=len(self._active_mock_body),
                    preview=self._active_mock_body[:200],
                )
                await self.execute(
                    fetch.fulfill_request(
                        request_id=fetch.RequestId(str(req_id)),
                        response_code=200,
                        body=b64_body,
                        response_headers=[
                            fetch.HeaderEntry(
                                name="Content-Type",
                                value="application/json+protobuf; charset=UTF-8",
                            ),
                            fetch.HeaderEntry(
                                name="Access-Control-Allow-Origin",
                                value="https://aistudio.google.com",
                            ),
                            fetch.HeaderEntry(
                                name="Access-Control-Allow-Credentials", value="true"
                            ),
                            fetch.HeaderEntry(name="X-Content-Type-Options", value="nosniff"),
                        ],
                    )
                )
                logger.info("aistudio.fetch.fulfilled_successfully")
                return

        if "GenerateContent" in url and method == "POST":
            post_data = req.get("postData")
            if not post_data:
                with contextlib.suppress(Exception):
                    post_data = await self.execute(
                        fetch.get_request_post_data(request_id=fetch.RequestId(str(req_id)))
                    )

            logger.info(
                "aistudio.fetch.generate_content_captured", body_preview=str(post_data)[:250]
            )

            body_dict: Any = {}
            if post_data:
                with contextlib.suppress(Exception):
                    body_dict = json.loads(post_data)

            if self._signature_future and not self._signature_future.done():
                self._signature_future.set_result(
                    {
                        "url": url,
                        "method": method,
                        "headers": req.get("headers", {}),
                        "body": body_dict,
                    }
                )
                logger.info("aistudio.signature.captured", url=url[:90])

            with contextlib.suppress(Exception):
                await self.execute(
                    fetch.fulfill_request(
                        request_id=fetch.RequestId(str(req_id)),
                        response_code=400,
                        body="",
                    )
                )
            return

        with contextlib.suppress(Exception):
            await self.execute(fetch.continue_request(request_id=fetch.RequestId(str(req_id))))

    async def _reader(self) -> None:
        pid = self.profile["id"]
        try:
            assert self._ws is not None
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                    msg_id = payload.get("id")

                    if msg_id is not None and msg_id in self._pending_cmds:
                        fut = self._pending_cmds.pop(msg_id)
                        if "error" in payload:
                            fut.set_exception(RuntimeError(payload["error"]))
                        else:
                            fut.set_result(payload.get("result", {}))
                    else:
                        method = payload.get("method", "")
                        params = payload.get("params", {})

                        if method == "Runtime.exceptionThrown":
                            details = params.get("exceptionDetails", {})
                            text = details.get("text", "")
                            exc = details.get("exception", {})
                            desc = exc.get("description", text)
                            logger.error(
                                "aistudio.browser.js_exception",
                                error=desc,
                                line=details.get("lineNumber"),
                                col=details.get("columnNumber"),
                                url=details.get("url"),
                            )
                        elif method == "Runtime.consoleAPICalled":
                            c_type = params.get("type", "log")
                            args = [
                                str(a.get("value", a.get("description", "")))
                                for a in params.get("args", [])
                            ]
                            log_msg = " ".join(args)
                            if c_type in ("error", "warning"):
                                logger.warning(
                                    "aistudio.browser.console", type=c_type, message=log_msg[:400]
                                )

                        if method == "Fetch.requestPaused":
                            asyncio.create_task(self._handle_fetch_event(params))
                            continue

                        event_session = payload.get("sessionId")
                        if self._current_session_id and event_session != self._current_session_id:
                            continue

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning(
                        "aistudio.ws.connection_closed", profile_id=pid, msg_type=str(msg.type)
                    )
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("aistudio.reader.exception", profile_id=pid, error=str(e))
        finally:
            for fut in list(self._pending_cmds.values()):
                if not fut.done():
                    fut.set_exception(ConnectionResetError("CDP WebSocket disconnected"))
            self._pending_cmds.clear()

    async def execute(
        self,
        cdp_generator: Generator[Any, Any, T],
        session_id: str | None = None,
    ) -> T:
        if not self.is_connected:
            raise RuntimeError("WebSocket is not connected")

        self._cmd_counter += 1
        cmd_id = self._cmd_counter
        req = cdp_generator.send(None)
        req["id"] = cmd_id

        method_name = req.get("method", "")
        target_session = (
            None if method_name.startswith("Target.") else (session_id or self._current_session_id)
        )

        if target_session:
            req["sessionId"] = str(target_session)

        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending_cmds[cmd_id] = fut
        try:
            await self._ws.send_json(req)
        except Exception as e:
            self._pending_cmds.pop(cmd_id, None)
            raise ConnectionResetError(f"Failed to send CDP command {method_name}: {e}") from e

        try:
            result = await asyncio.wait_for(fut, timeout=15.0)
        except TimeoutError:
            self._pending_cmds.pop(cmd_id, None)
            raise RuntimeError(f"CDP command {req.get('method')} timed out after 15s")

        try:
            cdp_generator.send(result)
        except StopIteration as e:
            return e.value

        raise RuntimeError("CDP generator did not finish with StopIteration")

    async def capture_error_screenshot(self, reason: str = "error") -> str | None:
        pid = self.profile.get("id", "unknown")
        if not self.is_connected:
            logger.warning("aistudio.error_screenshot_skipped", profile_id=pid, reason="ws_closed")
            return None
        try:
            dest = _format_screenshot_path(pid, reason)
            raw_bytes = await self.shot()
            dest.write_bytes(raw_bytes)
            with contextlib.suppress(Exception):
                latest = dest.parent / "latest.png"
                latest.write_bytes(raw_bytes)
            logger.warning(
                "aistudio.error_screenshot_captured",
                profile_id=pid,
                path=str(dest),
                reason=reason,
                bytes=len(raw_bytes),
            )
            return str(dest)
        except Exception as e:
            logger.warning("aistudio.error_screenshot_failed", profile_id=pid, error=str(e))
            return None

    async def __aenter__(self) -> Self:
        profile_id = self.profile["id"]
        logger.info("aistudio.browser.entering", profile_id=profile_id)
        await asyncio.to_thread(_start_profile_headless, self.endpoint, profile_id)

        ws_base = self.endpoint.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/playwright/{profile_id}"

        last_err = None
        for attempt in range(30):
            try:
                self._ws = await self.session.ws_connect(
                    ws_url,
                    max_msg_size=0,
                    heartbeat=15.0,
                )
                logger.info("aistudio.ws.connected", profile_id=profile_id, attempt=attempt + 1)
                break
            except Exception as err:
                last_err = err
                await asyncio.sleep(0.5)

        if self._ws is None or self._ws.closed:
            logger.error("aistudio.ws.failed", profile_id=profile_id, error=str(last_err))
            raise RuntimeError(f"Cannot connect to Kameleo WS at {ws_url}: {last_err}")

        self._reader_task = asyncio.create_task(self._reader())

        targets = await self.execute(target.get_targets())
        page_target = next((t for t in targets if t.type_ == "page"), None)

        if page_target is None:
            target_id = await self.execute(target.create_target(url="about:blank"))
        else:
            target_id = page_target.target_id

        self._current_target_id = str(target_id)
        attached_session = await self.execute(
            target.attach_to_target(target_id=target_id, flatten=True)
        )
        self._current_session_id = str(attached_session)
        logger.info(
            "aistudio.cdp.attached",
            profile_id=profile_id,
            target_id=self._current_target_id,
            session_id=self._current_session_id,
        )

        await self.execute(network.enable())
        await self.execute(page.enable())
        await self.execute(runtime.enable())

        with contextlib.suppress(Exception):
            await self.execute(emulation.set_focus_emulation_enabled(enabled=True))
        with contextlib.suppress(Exception):
            await self.execute(emulation.set_cpu_throttling_rate(rate=1.0))

        return self

    async def close(self) -> None:
        profile_id = self.profile["id"]
        logger.info("aistudio.browser.closing", profile_id=profile_id)

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self._reader_task = None

        for fut in list(self._pending_cmds.values()):
            if not fut.done():
                fut.set_exception(ConnectionResetError("CDP browser closed"))
        self._pending_cmds.clear()

        if self._ws and not self._ws.closed:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._ws = None

        stop_url = f"{self.endpoint}/profiles/{profile_id}/stop"
        try:
            async with self.session.post(stop_url, json={}) as resp:
                if resp.status == 404:
                    fallback_url = f"{self.endpoint}/profile/{profile_id}/stop"
                    async with self.session.post(fallback_url, json={}):
                        pass
        except Exception:
            pass
        logger.info("aistudio.browser.closed", profile_id=profile_id)

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            await self.capture_error_screenshot(reason=str(exc_type))
        await self.close()

    async def _query_element_center(self, selector_js: str) -> dict[str, float] | None:
        eval_cmd = runtime.evaluate(expression=selector_js, return_by_value=True)
        remote_object, _ = await self.execute(eval_cmd)
        if remote_object and isinstance(remote_object.value, dict):
            return {
                "x": float(remote_object.value["x"]),
                "y": float(remote_object.value["y"]),
            }
        return None

    async def _dismiss_interfering_dialogs(self) -> None:
        terms_js = """
        (() => {
            const isVisible = (el) => el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
            const allText = document.body ? (document.body.innerText || '') : '';
            if (!/terms of service|agreements|developer building with google ai studio/i.test(allText)) {
                return null;
            }
            const checkboxes = Array.from(document.querySelectorAll('mat-checkbox, [role="checkbox"], input[type="checkbox"]')).filter(isVisible);
            for (const cb of checkboxes) {
                if (cb.tagName === 'INPUT') {
                    if (!cb.checked) {
                        cb.click();
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                } else {
                    const isChecked = cb.classList.contains('mat-mdc-checkbox-checked') ||
                                      cb.classList.contains('mat-checkbox-checked') ||
                                      cb.getAttribute('aria-checked') === 'true' ||
                                      (cb.querySelector('input') && cb.querySelector('input').checked);
                    if (!isChecked) {
                        const target = cb.querySelector('label, .mdc-checkbox, input') || cb;
                        target.click();
                    }
                }
            }
            const candidates = Array.from(document.querySelectorAll('button, [role="button"]')).filter(isVisible);
            const continueBtn = candidates.find(b => {
                const text = (b.textContent || '').trim().toLowerCase();
                return text === 'continue' || text === 'agree' || text === 'i agree' || text === 'get started';
            });
            if (continueBtn) {
                const r = continueBtn.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            return null;
        })()
        """
        terms_coords = await self._query_element_center(terms_js)
        if terms_coords:
            logger.info("aistudio.dialog.terms_continue_clicked", coords=terms_coords)
            await self.mouse.click_at(terms_coords["x"], terms_coords["y"])
            await asyncio.sleep(0.5)

        cookie_js = """
        (() => {
            const isVisible = (el) => el && el.getBoundingClientRect().width > 0;
            const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]')).filter(isVisible);
            const btn = candidates.find(el => {
                const t = (el.textContent || '').trim().toLowerCase();
                return t === 'ok, got it' || t === 'accept all' || t === 'i agree';
            });
            if (btn) {
                const r = btn.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            return null;
        })()
        """
        cookie_coords = await self._query_element_center(cookie_js)
        if cookie_coords:
            logger.info("aistudio.dialog.cookie_clicked", coords=cookie_coords)
            await self.mouse.click_at(cookie_coords["x"], cookie_coords["y"])
            await asyncio.sleep(0.4)

    async def _send_ctrl_enter(self) -> None:
        await self.execute(
            input_.dispatch_key_event(
                type_="rawKeyDown",
                windows_virtual_key_code=17,
                key="Control",
                code="ControlLeft",
            )
        )
        await self.execute(
            input_.dispatch_key_event(
                type_="rawKeyDown",
                windows_virtual_key_code=13,
                key="Enter",
                code="Enter",
                modifiers=2,
            )
        )
        await self.execute(
            input_.dispatch_key_event(
                type_="keyUp",
                windows_virtual_key_code=13,
                key="Enter",
                code="Enter",
                modifiers=2,
            )
        )
        await self.execute(
            input_.dispatch_key_event(
                type_="keyUp",
                windows_virtual_key_code=17,
                key="Control",
                code="ControlLeft",
            )
        )

    def _get_proxy_url(self) -> str | None:
        proxy_info = self.profile.get("proxy")
        if not proxy_info:
            return None
        server = proxy_info.get("server")
        port = proxy_info.get("port")
        if not server or not port:
            return None
        user = proxy_info.get("username")
        pwd = proxy_info.get("password")
        if user and pwd:
            return f"http://{user}:{pwd}@{server}:{port}"
        return f"http://{server}:{port}"

    async def generate_content(self, prompt: str, timeout: float = 60.0) -> str:
        pid = self.profile["id"]
        logger.info(
            "aistudio.browser.generate_content.started",
            profile_id=pid,
            prompt_len=len(prompt),
            timeout=timeout,
        )
        mouse = self.mouse

        prompt_id = f"biba_{secrets.token_hex(4)}"
        alkali_data = _build_alkali_resource(prompt_id, prompt)
        self._active_mock_body = json.dumps(alkali_data)
        self._signature_future = asyncio.get_running_loop().create_future()

        try:
            await self.execute(
                fetch.enable(
                    patterns=[
                        fetch.RequestPattern(
                            url_pattern="*ResolveDriveResource*",
                            request_stage=fetch.RequestStage.REQUEST,
                        ),
                        fetch.RequestPattern(
                            url_pattern="*GenerateContent*",
                            request_stage=fetch.RequestStage.REQUEST,
                        ),
                    ]
                )
            )

            target_url = f"https://aistudio.google.com/prompts/{prompt_id}"
            logger.info("aistudio.navigation.page_navigate", url=target_url)
            await self.execute(page.navigate(url=target_url))

            run_btn_js = """
            (() => {
                const isVisible = (el) => el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
                const selectors = [
                    ".ctrl-enter-submits"
                ];
                for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (isVisible(el)) {
                        const r = el.getBoundingClientRect();
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                }
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(isVisible);
                const btn = buttons.find(b => {
                    const text = (b.textContent || '').trim();
                    const aria = (b.getAttribute('aria-label') || '').trim();
                    return /^run/i.test(text) || text.includes('Run') || /^run/i.test(aria);
                });
                if (btn) {
                    const r = btn.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
                return null;
            })()
            """

            run_coords = None
            logger.info("aistudio.ui.waiting_for_run_button")
            for attempt in range(40):
                await self._dismiss_interfering_dialogs()
                run_coords = await self._query_element_center(run_btn_js)
                if run_coords:
                    logger.info("aistudio.ui.run_button_found", attempt=attempt)
                    break
                await asyncio.sleep(0.5)

            if run_coords:
                logger.info("aistudio.input.clicking_run_button", coords=run_coords)
                await mouse.click_at(run_coords["x"], run_coords["y"])
            else:
                ui_state = await self.dump_ui_state()
                logger.warning("aistudio.input.run_not_found_dumping_ui", **ui_state)
                await self.capture_error_screenshot(reason="run_btn_missing")
                logger.warning("aistudio.input.run_fallback_ctrl_enter")
                await self._send_ctrl_enter()

            try:
                sig = await asyncio.wait_for(self._signature_future, timeout=20.0)
            except TimeoutError:
                await self.capture_error_screenshot(reason="signature_timeout")
                logger.warning("aistudio.signature.timeout", profile_id=pid)
                raise TimeoutError("Failed to intercept GenerateContent signature from AI Studio")

            with contextlib.suppress(Exception):
                await self.execute(fetch.disable())

            headers = {
                k: v
                for k, v in sig["headers"].items()
                if not k.startswith(":")
                and k.lower() not in ("host", "content-length", "transfer-encoding", "connection")
            }

            proxy_url = self._get_proxy_url()
            logger.info("aistudio.http.replaying_request", url=sig["url"][:120])

            async with self.session.request(
                method=sig["method"],
                url=sig["url"],
                headers=headers,
                json=sig.get("body") or {},
                proxy=proxy_url,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 429:
                    raise RateLimitError(
                        f"Profile {pid} received HTTP 429 Rate Limit from AI Studio"
                    )
                if resp.status != 200:
                    err_txt = await resp.text()
                    raise RuntimeError(f"AI Studio HTTP {resp.status}: {err_txt[:250]}")

                response_bytes = await resp.read()
                raw_text = response_bytes.decode("utf-8", errors="replace")

            final_text = extract_gemini_text(raw_text)
            if not final_text:
                logger.error(
                    "aistudio.browser.parse_failed", profile_id=pid, raw_preview=raw_text[:200]
                )
                raise RuntimeError(f"Failed to parse text from AI Studio response on profile {pid}")

            logger.info(
                "aistudio.browser.generate_content.success", profile_id=pid, length=len(final_text)
            )
            return clean_model_response(final_text)

        except Exception as e:
            await self.capture_error_screenshot(reason=type(e).__name__)
            logger.warning("aistudio.browser.generate_failed", profile_id=pid, error=str(e))
            raise
        finally:
            self._active_mock_body = None
            self._signature_future = None
            with contextlib.suppress(Exception):
                await self.execute(fetch.disable())

    async def shot(self) -> bytes:
        b64_data = await self.execute(page.capture_screenshot(format_="png"))
        return base64.b64decode(b64_data)
