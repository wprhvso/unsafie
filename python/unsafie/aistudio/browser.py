from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import random
from typing import TYPE_CHECKING, Any, Self, TypeVar

import aiohttp
import structlog
from pycdp.cdp import fetch, input_, network, page, runtime, target

from .formatter import clean_model_response
from .mouse import HumanMouse

if TYPE_CHECKING:
    from collections.abc import Generator

logger = structlog.get_logger()
T = TypeVar("T")


class RateLimitError(RuntimeError):
    pass


def extract_gemini_text(raw_data: Any) -> str:
    if isinstance(raw_data, str):
        text = raw_data.strip()
        if text.startswith(")]}'"):
            text = text[4:].strip()
        try:
            raw_data = json.loads(text)
        except Exception:
            lines = [line for line in text.splitlines() if line.startswith("data:")]
            if lines:
                parts = []
                for line in lines:
                    try:
                        parsed = json.loads(line[5:].strip())
                        sub = extract_gemini_text(parsed)
                        if sub:
                            parts.append(sub)
                    except Exception:
                        pass
                if parts:
                    return "".join(parts)
            return text

    if isinstance(raw_data, dict):
        if raw_data.get("candidates"):
            cand = raw_data["candidates"][0]
            parts = cand.get("content", {}).get("parts", [])
            text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p]
            if text_parts:
                return "".join(text_parts)
        if "error" in raw_data:
            err = raw_data["error"]
            code = err.get("code") or err.get("status")
            msg = err.get("message", "Error")
            if code == 429 or "RESOURCE_EXHAUSTED" in str(code):
                msg_0 = f"Google AI Studio rate limit (429): {msg}"
                raise RateLimitError(msg_0)
            msg_0 = f"API Error {code}: {msg}"
            raise RuntimeError(msg_0)

    if isinstance(raw_data, list):
        collected_texts: list[str] = []
        chunks = raw_data[0] if (raw_data and isinstance(raw_data[0], list)) else raw_data
        for chunk in chunks:
            if not isinstance(chunk, list) or not chunk:
                continue
            try:
                part = chunk[0][0][0][0][0]
                if isinstance(part, list) and len(part) > 1:
                    cand_str = part[1]
                    is_thought = len(part) > 12 and part[12] == 1
                    if isinstance(cand_str, str) and cand_str and not is_thought:
                        collected_texts.append(cand_str)
            except (IndexError, TypeError):
                continue
        if collected_texts:
            return "".join(collected_texts)

        found: list[str] = []

        def _walk(node: Any) -> None:
            if isinstance(node, str):
                if len(node) > 0 and not node.startswith("v1_"):
                    found.append(node)
            elif isinstance(node, list):
                for x in node:
                    _walk(x)
            elif isinstance(node, dict):
                for k, v in node.items():
                    if k == "text" and isinstance(v, str):
                        found.append(v)
                    else:
                        _walk(v)

        _walk(raw_data)
        if found:
            return max(found, key=len)

    return ""


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
        self._inflight_requests: int = 0
        self._last_network_activity: float = 0.0
        self._fetch_paused_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._error_screenshot_taken: bool = False

    async def _reader(self) -> None:
        log = logger.bind(component="AistudioBrowser", profile_id=self.profile["id"])
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
                        event_session = payload.get("sessionId")
                        if self._current_session_id and event_session != self._current_session_id:
                            continue

                        method = payload.get("method", "")
                        loop_time = asyncio.get_running_loop().time()

                        if method == "Fetch.requestPaused":
                            self._fetch_paused_queue.put_nowait(payload.get("params", {}))
                        elif method == "Network.requestWillBeSent":
                            self._inflight_requests += 1
                            self._last_network_activity = loop_time
                        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
                            self._inflight_requests = max(0, self._inflight_requests - 1)
                            self._last_network_activity = loop_time
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    log.warning("ws_connection_closed", msg_type=str(msg.type))
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("reader_fatal_exception", error=str(e))

    async def execute(
        self,
        cdp_generator: Generator[Any, Any, T],
        session_id: str | None = None,
    ) -> T:
        if self._ws is None or self._ws.closed:
            msg = "WebSocket is not connected"
            raise RuntimeError(msg)

        self._cmd_counter += 1
        cmd_id = self._cmd_counter
        req = cdp_generator.send(None)
        req["id"] = cmd_id

        method_name = req.get("method", "")
        if method_name.startswith("Target."):
            target_session = None
        else:
            target_session = session_id or self._current_session_id

        if target_session:
            req["sessionId"] = str(target_session)

        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending_cmds[cmd_id] = fut
        await self._ws.send_json(req)

        result = await fut
        try:
            cdp_generator.send(result)
        except StopIteration as e:
            return e.value

        msg = "CDP generator did not finish with StopIteration"
        raise RuntimeError(msg)

    async def capture_error_screenshot(self, filename: str = "screenshot_error.png") -> None:
        if self._error_screenshot_taken:
            return
        try:
            raw_bytes = await self.shot()
            with open(filename, "wb") as f:
                f.write(raw_bytes)
            self._error_screenshot_taken = True
        except Exception:
            pass

    async def __aenter__(self) -> Self:
        profile_id = self.profile["id"]
        start_url = f"{self.endpoint}/profiles/{profile_id}/start"
        async with self.session.post(start_url, json={}) as resp:
            if resp.status == 404:
                fallback_url = f"{self.endpoint}/profile/{profile_id}/start"
                async with self.session.post(fallback_url, json={}):
                    pass

        ws_base = self.endpoint.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_base}/playwright/{profile_id}"

        self._ws = await self.session.ws_connect(ws_url, max_msg_size=0)
        self._last_network_activity = asyncio.get_running_loop().time()
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

        await self.execute(network.enable())
        await self.execute(page.enable())
        await self.execute(runtime.enable())
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        profile_id = self.profile["id"]
        if exc_type is not None:
            await self.capture_error_screenshot()

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task

        if self._ws and not self._ws.closed:
            await self._ws.close()

        stop_url = f"{self.endpoint}/profiles/{profile_id}/stop"
        async with self.session.post(stop_url, json={}) as resp:
            if resp.status == 404:
                fallback_url = f"{self.endpoint}/profile/{profile_id}/stop"
                async with self.session.post(fallback_url, json={}):
                    pass

    async def wait(self, idle_time: float = 0.5, timeout: float = 30.0) -> None:
        await asyncio.sleep(0.3)
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        while loop.time() - start_time < timeout:
            now = loop.time()
            if self._inflight_requests == 0 and (now - self._last_network_activity >= idle_time):
                return
            await asyncio.sleep(0.1)

    async def _query_element_center(self, selector_js: str) -> dict[str, float] | None:
        eval_cmd = runtime.evaluate(expression=selector_js, return_by_value=True)
        remote_object, _ = await self.execute(eval_cmd)
        if remote_object and isinstance(remote_object.value, dict):
            return {
                "x": float(remote_object.value["x"]),
                "y": float(remote_object.value["y"]),
            }
        return None

    async def _wait_for_element_center(
        self,
        selector_js: str,
        timeout: float = 20.0,
        mouse: HumanMouse | None = None,
    ) -> dict[str, float]:
        start = asyncio.get_running_loop().time()
        poll_count = 0
        while asyncio.get_running_loop().time() - start < timeout:
            if mouse and poll_count % 3 == 0:
                await self._dismiss_interfering_dialogs(mouse=mouse)
            coords = await self._query_element_center(selector_js)
            if coords is not None:
                return coords
            poll_count += 1
            await asyncio.sleep(0.3)
        msg = f"Element not found within {timeout} seconds"
        raise TimeoutError(msg)

    async def _dismiss_interfering_dialogs(self, mouse: HumanMouse) -> bool:
        dismissed = False

        drive_cancel_js = """
        (() => {
            const isVisible = (el) => el && el.getBoundingClientRect().width > 0;
            const candidates = Array.from(document.querySelectorAll('button, [role="button"]')).filter(isVisible);
            const directCancel = candidates.find(b =>
                (b.textContent || '').trim().toLowerCase().includes('cancel and use temporary chat')
            );
            if (directCancel) {
                const r = directCancel.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            return null;
        })()
        """
        drive_cancel = await self._query_element_center(drive_cancel_js)
        if drive_cancel:
            await mouse.click_at(drive_cancel["x"], drive_cancel["y"])
            await asyncio.sleep(random.uniform(0.5, 0.8))
            dismissed = True

        upgrade_close_js = """
        (() => {
            const isVisible = (el) => el && el.getBoundingClientRect().width > 0;
            const allElements = Array.from(document.querySelectorAll('*'));
            const upgradeTitle = allElements.find(el =>
                el.children.length === 0 &&
                el.textContent &&
                el.textContent.trim().toLowerCase().includes('upgrade to unlock more') &&
                isVisible(el)
            );
            if (!upgradeTitle) return null;
            const container = upgradeTitle.closest('mat-dialog-container, [role="dialog"], .mat-mdc-dialog-container, div') || document;
            const candidates = Array.from(container.querySelectorAll('button, [role="button"]')).filter(isVisible);
            for (const b of candidates) {
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                const text = (b.textContent || '').trim().toLowerCase();
                if (aria.includes('close') || aria.includes('dismiss') || text === '×' || text === 'close') {
                    const r = b.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
            }
            return null;
        })()
        """
        upgrade_close = await self._query_element_center(upgrade_close_js)
        if upgrade_close:
            await mouse.click_at(upgrade_close["x"], upgrade_close["y"])
            await asyncio.sleep(random.uniform(0.5, 0.8))
            dismissed = True

        return dismissed

    async def _handle_welcome_dialog(self) -> None:
        click_all_js = """
        (() => {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => { if (!cb.checked) cb.click(); });
            const btn = Array.from(document.querySelectorAll('button, [role="button"]'))
                .find(el => el.textContent && el.textContent.trim().toLowerCase() === 'continue');
            if (btn) btn.click();
        })()
        """
        await self.execute(runtime.evaluate(expression=click_all_js))
        await self.wait()

    async def _handle_cookie_banner(self) -> None:
        cookie_js = """
        (() => {
            const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'))
                .filter(el => el.textContent && el.textContent.trim().toLowerCase() === 'ok, got it');
            if (candidates.length > 0) candidates[0].click();
        })()
        """
        await self.execute(runtime.evaluate(expression=cookie_js))

    async def _switch_to_free_model(self, mouse: HumanMouse) -> None:
        await self._dismiss_interfering_dialogs(mouse=mouse)

        check_model_js = """
        (() => {
            const card = document.querySelector('.model-selector-card, ms-model-select, [aria-label="Select a model"]');
            return card && card.textContent && /flash/i.test(card.textContent);
        })()
        """
        is_already_free, _ = await self.execute(
            runtime.evaluate(expression=check_model_js, return_by_value=True)
        )
        if is_already_free and is_already_free.value:
            return

        model_card_js = """
        (() => {
            const card = document.querySelector('.model-selector-card, ms-model-select, [aria-label="Select a model"]');
            if (card && card.getBoundingClientRect().width > 0) {
                const r = card.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            return null;
        })()
        """
        card_coords = await self._query_element_center(model_card_js)
        if card_coords:
            await mouse.click_at(card_coords["x"], card_coords["y"])
            await asyncio.sleep(0.8)

            search_js = """
            (() => {
                const s = document.querySelector('[aria-label="Search"], input[placeholder*="Search"]');
                if (s && s.getBoundingClientRect().width > 0) {
                    s.value = '';
                    s.focus();
                    const r = s.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
                return null;
            })()
            """
            s_coords = await self._query_element_center(search_js)
            if s_coords:
                await mouse.click_at(s_coords["x"], s_coords["y"])
                await self.execute(input_.insert_text(text="Flash"))
                await asyncio.sleep(0.8)

                row_js = """
                (() => {
                    const rows = Array.from(document.querySelectorAll('ms-model-carousel-row, .model-row'))
                        .filter(r => r.getBoundingClientRect().width > 0);
                    const target = rows.find(r => r.textContent && /flash/i.test(r.textContent)) || rows[0];
                    if (target) {
                        const r = target.getBoundingClientRect();
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                    return null;
                })()
                """
                row_coords = await self._query_element_center(row_js)
                if row_coords:
                    await mouse.click_at(row_coords["x"], row_coords["y"])
                    await asyncio.sleep(1.0)

    async def monopolize_tabs(self, url: str = "https://aistudio.google.com") -> None:
        targets = await self.execute(target.get_targets())
        old_page_ids = [t.target_id for t in targets if t.type_ == "page"]

        new_target_id = await self.execute(target.create_target(url="about:blank"))
        await self.execute(target.activate_target(target_id=new_target_id))

        new_session_id = await self.execute(
            target.attach_to_target(target_id=new_target_id, flatten=True)
        )
        self._current_target_id = str(new_target_id)
        self._current_session_id = str(new_session_id)
        self._inflight_requests = 0
        self._last_network_activity = asyncio.get_running_loop().time()

        await self.execute(network.enable())
        await self.execute(page.enable())
        await self.execute(runtime.enable())

        for old_id in old_page_ids:
            if str(old_id) != str(new_target_id):
                with contextlib.suppress(Exception):
                    await self.execute(target.close_target(target_id=old_id))

        await self.execute(page.navigate(url=url))
        await self.wait()
        await self._handle_welcome_dialog()
        await self._handle_cookie_banner()

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

    async def reset_new_chat(self, mouse: HumanMouse) -> None:
        new_chat_js = """
        (() => {
            const isVisible = el => el && el.getBoundingClientRect().width > 0;
            const a = document.querySelector('a[href*="new_chat"], button[aria-label*="New prompt"], [data-test-id="new-chat-button"]');
            if (isVisible(a)) {
                const r = a.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            return null;
        })()
        """
        coords = await self._query_element_center(new_chat_js)
        if coords:
            await mouse.click_at(coords["x"], coords["y"])
            await asyncio.sleep(1.0)
            await self._dismiss_interfering_dialogs(mouse=mouse)
        else:
            await self.execute(page.navigate(url="https://aistudio.google.com/prompts/new_chat"))
            await self.wait()
            await self._handle_welcome_dialog()
            await self._handle_cookie_banner()

    async def generate_content(self, prompt: str, timeout: float = 60.0) -> str:
        log = logger.bind(component="AistudioBrowser", profile_id=self.profile["id"])
        mouse = HumanMouse(browser=self)

        await self.reset_new_chat(mouse=mouse)
        await self._switch_to_free_model(mouse=mouse)

        prompt_input_js = """
        (() => {
            const isVisible = el => el && el.getBoundingClientRect().width > 0;
            const input = document.querySelector(
                '[aria-label="Enter a prompt"], textarea[aria-label="Enter a prompt"], .prompt-box textarea, ms-prompt-editor textarea, [contenteditable="true"]'
            );
            if (isVisible(input)) {
                const r = input.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            return null;
        })()
        """
        input_coords = await self._wait_for_element_center(
            prompt_input_js, timeout=20.0, mouse=mouse
        )
        await mouse.click_at(input_coords["x"], input_coords["y"])
        await asyncio.sleep(0.3)

        await self.execute(
            fetch.enable(
                patterns=[
                    fetch.RequestPattern(
                        url_pattern="*alkalimakersuite-pa*GenerateContent*",
                        request_stage=fetch.RequestStage.REQUEST,
                    ),
                    fetch.RequestPattern(
                        url_pattern="*alkalimakersuite-pa*GenerateContent*",
                        request_stage=fetch.RequestStage.RESPONSE,
                    ),
                ]
            )
        )

        set_prompt_js = """
        ((promptText) => {
            const target = document.activeElement || document.querySelector('textarea, [contenteditable="true"]');
            if (!target) return false;
            target.focus();
            if (target.isContentEditable || target.getAttribute('contenteditable') === 'true') {
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, promptText);
                target.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, inputType: 'insertText', data: promptText }));
            } else {
                const proto = target instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) setter.call(target, promptText); else target.value = promptText;
                target.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
                target.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
            }
            return true;
        })(__PROMPT_TEXT__)
        """.replace("__PROMPT_TEXT__", json.dumps(prompt))

        eval_res, _ = await self.execute(
            runtime.evaluate(expression=set_prompt_js, return_by_value=True)
        )
        if not eval_res or not eval_res.value:
            await self.execute(input_.insert_text(text=prompt))

        await asyncio.sleep(0.3)
        await self._send_ctrl_enter()

        loop = asyncio.get_running_loop()
        start = loop.time()
        final_text = ""

        try:
            while loop.time() - start < timeout:
                try:
                    paused = await asyncio.wait_for(self._fetch_paused_queue.get(), timeout=2.0)
                except TimeoutError:
                    await self._dismiss_interfering_dialogs(mouse=mouse)
                    continue

                req_id = str(paused.get("requestId"))
                status_code = paused.get("responseStatusCode")

                if status_code is None:
                    req_method = paused.get("request", {}).get("method", "").upper()
                    if req_method == "OPTIONS":
                        await self.execute(
                            fetch.continue_request(request_id=fetch.RequestId(req_id))
                        )
                        continue

                    await self.execute(fetch.continue_request(request_id=fetch.RequestId(req_id)))
                    continue

                if status_code == 429:
                    with contextlib.suppress(Exception):
                        await self.execute(
                            fetch.continue_request(request_id=fetch.RequestId(req_id))
                        )
                    msg = f"Profile {self.profile['id']} received HTTP 429 Rate Limit from AI Studio"
                    raise RateLimitError(
                        msg
                    )

                if status_code != 200:
                    with contextlib.suppress(Exception):
                        await self.execute(
                            fetch.continue_request(request_id=fetch.RequestId(req_id))
                        )
                    msg = f"Google AI Studio error status HTTP {status_code}"
                    raise RuntimeError(msg)

                try:
                    body_raw, is_b64 = await self.execute(
                        fetch.get_response_body(request_id=fetch.RequestId(req_id))
                    )
                    if is_b64:
                        body_decoded = base64.b64decode(body_raw).decode("utf-8", errors="replace")
                    else:
                        body_decoded = body_raw
                    final_text = extract_gemini_text(body_decoded)
                except Exception as e:
                    log.warning("could_not_read_response_body", error=str(e))
                finally:
                    with contextlib.suppress(Exception):
                        await self.execute(
                            fetch.continue_request(request_id=fetch.RequestId(req_id))
                        )

                if final_text:
                    break
        finally:
            with contextlib.suppress(Exception):
                await self.execute(fetch.disable())

        if not final_text:
            await asyncio.sleep(2.5)
            dom_js = """
            (() => {
                const turns = Array.from(document.querySelectorAll('ms-chat-turn, .model-turn, .chat-turn'));
                if (turns.length > 0) {
                    const lastTurn = turns[turns.length - 1];
                    const content = lastTurn.querySelector('.markdown-wrapper, ms-text-chunk, .rendered-markdown') || lastTurn;
                    return content.innerText || content.textContent || '';
                }
                return '';
            })()
            """
            dom_res, _ = await self.execute(
                runtime.evaluate(expression=dom_js, return_by_value=True)
            )
            if dom_res and isinstance(dom_res.value, str):
                final_text = dom_res.value

        if not final_text:
            msg = f"Failed to receive completion from AI Studio on profile {self.profile['id']}"
            raise RuntimeError(
                msg
            )

        return clean_model_response(final_text)

    async def shot(self) -> bytes:
        b64_data = await self.execute(page.capture_screenshot(format_="png"))
        return base64.b64decode(b64_data)
