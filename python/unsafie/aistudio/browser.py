from __future__ import annotations

import asyncio
import base64
import collections
import contextlib
import json
import random
import shutil
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
                raise RateLimitError(f"Google AI Studio rate limit (429): {msg}")
            raise RuntimeError(f"API Error {code}: {msg}")

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


def _format_video_path(profile_id: str, reason: str = "") -> Path:
    p = _format_screenshot_path(profile_id, reason)
    return p.with_suffix(".mp4")


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

        self._frame_buffer: collections.deque[bytes] = collections.deque(maxlen=150)
        self._recorder_task: asyncio.Task[None] | None = None
        self._recording: bool = False

        self.mouse = HumanMouse(browser=self)
        self._is_busy: bool = False
        self._idle_mouse_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    def start_recording(self) -> None:
        self._recording = True
        self._frame_buffer.clear()
        if self._recorder_task is None or self._recorder_task.done():
            self._recorder_task = asyncio.create_task(self._record_loop())

    def stop_recording(self) -> None:
        self._recording = False
        if self._recorder_task and not self._recorder_task.done():
            self._recorder_task.cancel()
        self._recorder_task = None

    async def _record_loop(self) -> None:
        while self._recording:
            try:
                if self.is_connected:
                    frame = await self.shot()
                    self._frame_buffer.append(frame)
            except Exception:
                pass
            await asyncio.sleep(0.25)

    async def _idle_mouse_loop(self) -> None:
        while True:
            try:
                if not self._is_busy and self.is_connected:
                    target_x = random.uniform(180, 1050)
                    target_y = random.uniform(140, 680)
                    await self.mouse.move_to(target_x, target_y)

                    if random.random() < 0.45:
                        await asyncio.sleep(random.uniform(0.15, 0.4))
                        await self.mouse.move_to(
                            target_x + random.uniform(-20, 20),
                            target_y + random.uniform(-20, 20),
                            steps=random.randint(6, 14),
                        )
                await asyncio.sleep(random.uniform(1.2, 2.8))
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2.0)

    async def _keepalive_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(12.0)
                if not self._is_busy and self.is_connected and self._current_session_id:
                    try:
                        res, _ = await asyncio.wait_for(
                            self.execute(
                                runtime.evaluate(expression="1 + 1", return_by_value=True)
                            ),
                            timeout=3.0,
                        )
                        if not res or res.value != 2:
                            logger.warning(
                                "aistudio.keepalive.unexpected_result",
                                profile_id=self.profile.get("id"),
                            )
                    except Exception as err:
                        logger.warning(
                            "aistudio.keepalive.failed",
                            profile_id=self.profile.get("id"),
                            error=str(err),
                        )
                        if self._ws and not self._ws.closed:
                            with contextlib.suppress(Exception):
                                await self._ws.close()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(4.0)

    async def ping(self, timeout: float = 2.0) -> bool:
        if not self.is_connected or not self._current_session_id:
            return False
        try:
            res, _ = await asyncio.wait_for(
                self.execute(runtime.evaluate(expression="1 + 1", return_by_value=True)),
                timeout=timeout,
            )
            return bool(res and res.value == 2)
        except Exception:
            return False

    async def capture_error_video(self, reason: str = "error") -> str | None:
        pid = self.profile.get("id", "unknown")
        shot_path = await self.capture_error_screenshot(reason=reason)

        if not self._frame_buffer:
            return shot_path

        video_path = _format_video_path(pid, reason)
        frames = list(self._frame_buffer)

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            logger.warning("aistudio.ffmpeg_not_found", profile_id=pid)
            return shot_path

        def _encode() -> bool:
            try:
                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-r",
                    "4",
                    "-i",
                    "-",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(video_path),
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                assert proc.stdin is not None
                for f in frames:
                    proc.stdin.write(f)
                proc.stdin.close()
                proc.wait(timeout=10)
                if video_path.exists() and video_path.stat().st_size > 0:
                    latest = video_path.parent / "latest.mp4"
                    with contextlib.suppress(Exception):
                        latest.write_bytes(video_path.read_bytes())
                    return True
            except Exception as e:
                logger.warning("aistudio.ffmpeg_encode_failed", error=str(e))
            return False

        success = await asyncio.to_thread(_encode)
        if success:
            logger.warning(
                "aistudio.error_video_captured",
                profile_id=pid,
                path=str(video_path),
                reason=reason,
                frames=len(frames),
                bytes=video_path.stat().st_size,
            )
            return str(video_path)
        return shot_path

    async def get_current_url(self) -> str:
        if not self.is_connected:
            return ""
        try:
            res, _ = await self.execute(
                runtime.evaluate(expression="window.location.href", return_by_value=True)
            )
            return str(res.value) if res and res.value else ""
        except Exception:
            return ""

    async def check_welcome_page(self) -> None:
        url = await self.get_current_url()
        if not url:
            return
        clean_url = url.lower()
        if (
            "aistudio.google.com/welcome" in clean_url
            or clean_url.rstrip("/").endswith("/welcome")
            or "accounts.google.com" in clean_url
        ):
            await self.capture_error_video(reason="welcome_page_detected")
            logger.warning(
                "aistudio.browser.welcome_page_detected",
                profile_id=self.profile.get("id"),
                url=url,
            )
            raise UnusableProfileError(f"Profile redirected to welcome or login page: {url}")

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
                        if (
                            method
                            in (
                                "Target.detachedFromTarget",
                                "Inspector.detached",
                                "Inspector.targetCrashed",
                            )
                            and params.get("sessionId") == self._current_session_id
                        ):
                            logger.warning(
                                "aistudio.cdp.session_invalidated",
                                profile_id=pid,
                                method=method,
                            )
                            self._current_session_id = None

                        event_session = payload.get("sessionId")
                        if self._current_session_id and event_session != self._current_session_id:
                            continue

                        loop_time = asyncio.get_running_loop().time()

                        if method == "Fetch.requestPaused":
                            params = payload.get("params", {})
                            url = params.get("request", {}).get("url", "")
                            stage = params.get("responseStatusCode")
                            logger.info(
                                "aistudio.cdp.fetch_paused",
                                profile_id=pid,
                                url=url[:150],
                                status=stage,
                            )
                            self._fetch_paused_queue.put_nowait(params)
                        elif method == "Network.requestWillBeSent":
                            self._inflight_requests += 1
                            self._last_network_activity = loop_time
                        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
                            self._inflight_requests = max(0, self._inflight_requests - 1)
                            self._last_network_activity = loop_time
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning(
                        "aistudio.ws.connection_closed",
                        profile_id=pid,
                        msg_type=str(msg.type),
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
        if method_name.startswith("Target."):
            target_session = None
        else:
            target_session = session_id or self._current_session_id

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
            logger.warning(
                "aistudio.error_screenshot_failed",
                profile_id=pid,
                error=str(e),
            )
            return None

    async def reconnect(self) -> None:
        profile_id = self.profile["id"]
        logger.info("aistudio.browser.reconnecting", profile_id=profile_id)

        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
        self._keepalive_task = None

        if self._idle_mouse_task and not self._idle_mouse_task.done():
            self._idle_mouse_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_mouse_task
        self._idle_mouse_task = None

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self._reader_task = None

        for fut in list(self._pending_cmds.values()):
            if not fut.done():
                fut.set_exception(ConnectionResetError("Reconnecting CDP"))
        self._pending_cmds.clear()

        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self._current_session_id = None
        self._current_target_id = None

        await self.__aenter__()
        await self.monopolize_tabs("https://aistudio.google.com")
        logger.info("aistudio.browser.reconnected", profile_id=profile_id)

    async def ensure_connected(self) -> None:
        if not self.is_connected:
            await self.reconnect()
            return

        alive = await self.ping(timeout=2.0)
        if not alive:
            logger.warning(
                "aistudio.browser.ping_failed_reconnecting",
                profile_id=self.profile.get("id"),
            )
            await self.reconnect()

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
            raise RuntimeError(f"Cannot connect to Kameleo Playwright WS at {ws_url}: {last_err}")

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

        if self._idle_mouse_task is None or self._idle_mouse_task.done():
            self._idle_mouse_task = asyncio.create_task(self._idle_mouse_loop())

        if self._keepalive_task is None or self._keepalive_task.done():
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        return self

    async def close(self, stop_profile: bool = False) -> None:
        profile_id = self.profile["id"]
        logger.info("aistudio.browser.closing", profile_id=profile_id, stop_profile=stop_profile)
        self.stop_recording()

        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
        self._keepalive_task = None

        if self._idle_mouse_task and not self._idle_mouse_task.done():
            self._idle_mouse_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_mouse_task
        self._idle_mouse_task = None

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
            await self._ws.close()
        self._ws = None

        if stop_profile:
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
            await self.capture_error_video(reason=str(exc_type))
        self.stop_recording()
        await self.close(stop_profile=False)

    async def wait(self, idle_time: float = 0.25, timeout: float = 4.0) -> None:
        await asyncio.sleep(0.15)
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        while loop.time() - start_time < timeout:
            now = loop.time()
            if self._inflight_requests == 0 and (now - self._last_network_activity >= idle_time):
                return
            await asyncio.sleep(0.08)

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
        timeout: float = 15.0,
        mouse: HumanMouse | None = None,
    ) -> dict[str, float]:
        m = mouse or self.mouse
        start = asyncio.get_running_loop().time()
        poll_count = 0
        while asyncio.get_running_loop().time() - start < timeout:
            if poll_count % 3 == 0:
                await self._dismiss_interfering_dialogs(mouse=m)
            coords = await self._query_element_center(selector_js)
            if coords is not None:
                return coords
            poll_count += 1
            await asyncio.sleep(0.25)

        await self.check_welcome_page()
        video_file = await self.capture_error_video(reason="element_wait_timeout")
        logger.warning(
            "aistudio.browser.element_timeout",
            profile_id=self.profile.get("id"),
            timeout=timeout,
            video_path=video_file,
        )
        raise TimeoutError(f"Element not found within {timeout} seconds")

    async def _dismiss_interfering_dialogs(self, mouse: HumanMouse) -> bool:
        dismissed = False

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
            await self.execute(
                runtime.evaluate(
                    expression="""
                    (() => {
                        const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
                        const btn = candidates.find(b => (b.textContent || '').trim().toLowerCase() === 'continue');
                        if (btn) btn.click();
                    })()
                    """
                )
            )
            await mouse.click_at(terms_coords["x"], terms_coords["y"])
            await asyncio.sleep(random.uniform(0.5, 0.8))
            dismissed = True

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
            logger.info("aistudio.dialog.drive_cancel_clicked", coords=drive_cancel)
            await mouse.click_at(drive_cancel["x"], drive_cancel["y"])
            await asyncio.sleep(random.uniform(0.3, 0.5))
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
            const container = upgradeTitle.closest('mat-dialog-container, [role="dialog"], .mat-mdc-dialog-container');
            if (!container) return null;
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
            logger.info("aistudio.dialog.upgrade_close_clicked", coords=upgrade_close)
            await mouse.click_at(upgrade_close["x"], upgrade_close["y"])
            await asyncio.sleep(random.uniform(0.3, 0.5))
            dismissed = True

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
            await mouse.click_at(cookie_coords["x"], cookie_coords["y"])
            await asyncio.sleep(random.uniform(0.3, 0.5))
            dismissed = True

        return dismissed

    async def _handle_welcome_dialog(self) -> None:
        await self._dismiss_interfering_dialogs(mouse=self.mouse)
        await self.wait(timeout=1.5)

    async def _handle_cookie_banner(self) -> None:
        cookie_js = """
        (() => {
            const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'))
                .filter(el => el.textContent && el.textContent.trim().toLowerCase() === 'ok, got it');
            if (candidates.length > 0) candidates[0].click();
        })()
        """
        await self.execute(runtime.evaluate(expression=cookie_js))

    async def _has_upgrade_to_unlock(self) -> bool:
        check_upgrade_js = """
        (() => {
            const main = document.querySelector('mat-sidenav-content, main, ms-playground, ms-prompt-editor, ms-prompt-run') || document.body;
            const text = (main ? (main.innerText || '') : '').toLowerCase();
            return text.includes('upgrade to unlock gemini') || 
                   text.includes('is only available in the playground via a google ai plan') ||
                   text.includes('upgrade to unlock access to more models');
        })()
        """
        try:
            res, _ = await self.execute(
                runtime.evaluate(expression=check_upgrade_js, return_by_value=True)
            )
            return bool(res and res.value)
        except Exception:
            return False

    async def _switch_to_free_model(self, mouse: HumanMouse) -> None:
        await self._dismiss_interfering_dialogs(mouse=mouse)

        has_upgrade = await self._has_upgrade_to_unlock()

        check_already_38_js = """
        (() => {
            const card = document.querySelector('.model-selector-card, ms-model-select, [aria-label="Select a model"], ms-run-settings');
            const text = card ? (card.textContent || '') : '';
            return text.includes('3.8') && /flash/i.test(text);
        })()
        """
        is_already_38, _ = await self.execute(
            runtime.evaluate(expression=check_already_38_js, return_by_value=True)
        )
        if not has_upgrade and is_already_38 and is_already_38.value:
            logger.info("aistudio.model.already_38_flash")
            return

        logger.info("aistudio.model.switching_needed", has_upgrade=has_upgrade)

        model_card_js = """
        (() => {
            const selectors = [
                '.model-selector-card',
                'ms-model-select',
                '[aria-label="Select a model"]',
                'button[aria-label*="Select a model" i]',
                '[data-test-id*="model-selector"]'
            ];
            for (const s of selectors) {
                const card = document.querySelector(s);
                if (card && card.getBoundingClientRect().width > 0) {
                    const r = card.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
            }
            return null;
        })()
        """

        card_coords = await self._query_element_center(model_card_js)
        if not card_coords:
            tune_btn_js = """
            (() => {
                const isVisible = (el) => el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
                const btn = document.querySelector('.runsettings-toggle-button, button.runsettings-toggle-button, [data-test-id*="runsettings"]');
                if (btn && isVisible(btn)) {
                    const r = btn.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(isVisible);
                const fallback = buttons.find(b => {
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    const text = (b.textContent || '').toLowerCase();
                    return aria.includes('run settings') || aria.includes('settings') || aria.includes('tune') || text.includes('tune');
                });
                if (fallback) {
                    const r = fallback.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
                return null;
            })()
            """
            tune_coords = await self._query_element_center(tune_btn_js)
            if tune_coords:
                logger.info("aistudio.model.opening_settings_drawer", coords=tune_coords)
                await mouse.click_at(tune_coords["x"], tune_coords["y"])
                for _ in range(12):
                    await asyncio.sleep(0.25)
                    card_coords = await self._query_element_center(model_card_js)
                    if card_coords:
                        break

        if not card_coords:
            raise RuntimeError("Model selector element not found on page")

        logger.info("aistudio.model.opening_selector", coords=card_coords)
        await mouse.click_at(card_coords["x"], card_coords["y"])
        await asyncio.sleep(0.5)

        search_js = """
        (() => {
            const selectors = [
                '[aria-label="Search"]',
                'input[placeholder*="Search"]',
                'input[placeholder*="Search" i]',
                'input[aria-label*="Search" i]',
                'input[type="search"]',
                'ms-model-picker input',
                '.mat-mdc-form-field input'
            ];
            for (const sel of selectors) {
                const s = document.querySelector(sel);
                if (s && s.getBoundingClientRect().width > 0) {
                    s.focus();
                    const r = s.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
            }
            return null;
        })()
        """
        s_coords = None
        for _ in range(10):
            s_coords = await self._query_element_center(search_js)
            if s_coords:
                break
            await asyncio.sleep(0.25)

        if not s_coords:
            raise RuntimeError("Search input in model selector not found")

        logger.info("aistudio.model.searching_flash", coords=s_coords)
        await mouse.click_at(s_coords["x"], s_coords["y"])

        clear_js = """
        (() => {
            const s = document.activeElement;
            if (s && 'value' in s) {
                s.value = '';
                s.dispatchEvent(new Event('input', { bubbles: true }));
            }
        })()
        """
        await self.execute(runtime.evaluate(expression=clear_js))
        await self.execute(input_.insert_text(text="3.8"))
        await asyncio.sleep(0.5)

        row_js = """
        (() => {
            const isVisible = (el) => el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
            const rows = Array.from(document.querySelectorAll('ms-model-carousel-row, .model-row, mat-list-item, [role="option"], ms-model-picker-row, .mat-mdc-list-item, .model-item'))
                .filter(isVisible);

            let target = rows.find(r => {
                const t = (r.textContent || '').toLowerCase();
                return t.includes('3.8') && t.includes('flash');
            });

            if (!target) {
                target = rows.find(r => (r.textContent || '').includes('3.8'));
            }

            if (!target) {
                target = rows.find(r => {
                    const t = (r.textContent || '').toLowerCase();
                    return t.includes('flash') && !t.includes('preview');
                });
            }

            if (!target && rows.length > 0) {
                target = rows[0];
            }

            if (target) {
                const r = target.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
            return null;
        })()
        """
        row_coords = None
        for _ in range(8):
            row_coords = await self._query_element_center(row_js)
            if row_coords:
                break
            await asyncio.sleep(0.25)

        if not row_coords:
            raise RuntimeError("No model row found matching search '3.8'")

        logger.info("aistudio.model.selecting_row", coords=row_coords)
        await mouse.click_at(row_coords["x"], row_coords["y"])
        await asyncio.sleep(0.8)

        if await self._has_upgrade_to_unlock():
            raise RuntimeError(
                "Failed to switch model: 'Upgrade to unlock Gemini' notice is still present"
            )

    async def monopolize_tabs(self, url: str = "https://aistudio.google.com") -> None:
        logger.info("aistudio.tabs.monopolize", url=url, profile_id=self.profile["id"])
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

        with contextlib.suppress(Exception):
            await self.execute(emulation.set_focus_emulation_enabled(enabled=True))
        with contextlib.suppress(Exception):
            await self.execute(emulation.set_cpu_throttling_rate(rate=1.0))

        for old_id in old_page_ids:
            if str(old_id) != str(new_target_id):
                with contextlib.suppress(Exception):
                    await self.execute(target.close_target(target_id=old_id))

        logger.info("aistudio.page.navigate", url=url)
        await self.execute(page.navigate(url=url))
        await self.wait(timeout=4.0)
        await self.check_welcome_page()
        await self._handle_welcome_dialog()
        await self._handle_cookie_banner()
        await self.check_welcome_page()
        logger.info("aistudio.tabs.monopolize.ready")

    async def _send_ctrl_enter(self) -> None:
        logger.info("aistudio.input.send_ctrl_enter")
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
        logger.info("aistudio.chat.reset")
        await self.check_welcome_page()
        await self._dismiss_interfering_dialogs(mouse=mouse)
        new_chat_js = """
        (() => {
            const isVisible = el => el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
            const selectors = [
                'a[href*="new_chat"]',
                'button[aria-label*="New prompt" i]',
                'button[aria-label*="New chat" i]',
                '[data-test-id="new-chat-button"]',
                '.new-prompt-button'
            ];
            for (const s of selectors) {
                const el = document.querySelector(s);
                if (isVisible(el)) {
                    const r = el.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
            }
            return null;
        })()
        """
        coords = await self._query_element_center(new_chat_js)
        if coords:
            logger.info("aistudio.chat.reset.clicking_button", coords=coords)
            await mouse.click_at(coords["x"], coords["y"])
            await asyncio.sleep(0.6)
            await self._dismiss_interfering_dialogs(mouse=mouse)
        else:
            logger.info("aistudio.chat.reset.navigating_url")
            await self.execute(page.navigate(url="https://aistudio.google.com/prompts/new_chat"))
            await self.wait(timeout=4.0)
            await self.check_welcome_page()
            await self._handle_welcome_dialog()
            await self._handle_cookie_banner()
        await self.check_welcome_page()

    async def generate_content(self, prompt: str, timeout: float = 60.0) -> str:
        pid = self.profile["id"]
        logger.info(
            "aistudio.browser.generate_content.started",
            profile_id=pid,
            prompt_len=len(prompt),
            timeout=timeout,
        )
        await self.ensure_connected()
        await self.check_welcome_page()
        mouse = self.mouse

        self._is_busy = True
        self.start_recording()

        try:
            await self._dismiss_interfering_dialogs(mouse=mouse)
            await self.reset_new_chat(mouse=mouse)
            await self.check_welcome_page()
            await self._dismiss_interfering_dialogs(mouse=mouse)

            await self._switch_to_free_model(mouse=mouse)

            prompt_input_js = """
            (() => {
                const isVisible = el => el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
                const candidates = [
                    ...document.querySelectorAll('textarea'),
                    ...document.querySelectorAll('[role="textbox"]'),
                    ...document.querySelectorAll('[contenteditable="true"]'),
                    ...document.querySelectorAll('[aria-label*="prompt" i]'),
                    ...document.querySelectorAll('[placeholder*="prompt" i]'),
                    ...document.querySelectorAll('[placeholder*="type" i]'),
                    ...document.querySelectorAll('.prompt-box textarea'),
                    ...document.querySelectorAll('ms-prompt-editor [contenteditable="true"]'),
                    ...document.querySelectorAll('div.ql-editor')
                ];
                for (const el of candidates) {
                    if (isVisible(el)) {
                        const r = el.getBoundingClientRect();
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                }
                return null;
            })()
            """
            coords = await self._query_element_center(prompt_input_js)
            if not coords:
                logger.info("aistudio.browser.navigating_direct_fallback")
                await self.execute(
                    page.navigate(url="https://aistudio.google.com/prompts/new_chat")
                )
                await self.wait(timeout=4.0)
                await self.check_welcome_page()
                await self._handle_welcome_dialog()
                await self._handle_cookie_banner()
                await self._dismiss_interfering_dialogs(mouse=mouse)

            await self._dismiss_interfering_dialogs(mouse=mouse)

            logger.info("aistudio.browser.waiting_for_input")
            input_coords = await self._wait_for_element_center(
                prompt_input_js, timeout=15.0, mouse=mouse
            )
            logger.info("aistudio.browser.input_found", coords=input_coords)
            await mouse.click_at(input_coords["x"], input_coords["y"])
            await asyncio.sleep(0.2)

            logger.info("aistudio.browser.enabling_fetch_interception")
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
                const target = document.activeElement || document.querySelector('textarea, [contenteditable="true"], [role="textbox"]');
                if (!target) return false;
                target.focus();
                if (target.isContentEditable || target.getAttribute('contenteditable') === 'true' || target.getAttribute('role') === 'textbox') {
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
                logger.info("aistudio.browser.typing_fallback")
                await self.execute(input_.insert_text(text=prompt))
            else:
                logger.info("aistudio.browser.prompt_injected_via_js")

            await asyncio.sleep(0.3)

            run_btn_js = """
            (() => {
                const isVisible = (el) => el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
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
            for _ in range(10):
                run_coords = await self._query_element_center(run_btn_js)
                if run_coords:
                    break
                await asyncio.sleep(0.1)

            if run_coords:
                logger.info("aistudio.input.clicking_run_button", coords=run_coords)
                await mouse.click_at(run_coords["x"], run_coords["y"])
            else:
                logger.warning("aistudio.input.run_button_not_found_fallback_ctrl_enter")
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
                    req_url = paused.get("request", {}).get("url", "")

                    logger.info(
                        "aistudio.browser.fetch_event_handling",
                        req_id=req_id,
                        status_code=status_code,
                        url=req_url[:120],
                    )

                    if status_code is None:
                        req_method = paused.get("request", {}).get("method", "").upper()
                        if req_method == "OPTIONS":
                            await self.execute(
                                fetch.continue_request(request_id=fetch.RequestId(req_id))
                            )
                            continue

                        await self.execute(
                            fetch.continue_request(request_id=fetch.RequestId(req_id))
                        )
                        continue

                    if status_code == 429:
                        logger.warning("aistudio.browser.received_429", profile_id=pid)
                        with contextlib.suppress(Exception):
                            await self.execute(
                                fetch.continue_request(request_id=fetch.RequestId(req_id))
                            )
                        raise RateLimitError(
                            f"Profile {pid} received HTTP 429 Rate Limit from AI Studio"
                        )

                    if status_code != 200:
                        logger.error("aistudio.browser.received_error_status", status=status_code)
                        with contextlib.suppress(Exception):
                            await self.execute(
                                fetch.continue_request(request_id=fetch.RequestId(req_id))
                            )
                        raise RuntimeError(f"Google AI Studio error status HTTP {status_code}")

                    try:
                        body_raw, is_b64 = await self.execute(
                            fetch.get_response_body(request_id=fetch.RequestId(req_id))
                        )
                        if is_b64:
                            body_decoded = base64.b64decode(body_raw).decode(
                                "utf-8", errors="replace"
                            )
                        else:
                            body_decoded = body_raw
                        final_text = extract_gemini_text(body_decoded)
                        logger.info(
                            "aistudio.browser.response_decoded",
                            profile_id=pid,
                            body_len=len(body_decoded),
                            extracted_len=len(final_text),
                        )
                    except Exception as e:
                        logger.warning("aistudio.browser.response_read_error", error=str(e))
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
                logger.info("aistudio.browser.checking_dom_fallback")
                await asyncio.sleep(2.0)
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
                    logger.info("aistudio.browser.dom_fallback_found", text_len=len(final_text))

            if not final_text:
                logger.error("aistudio.browser.completion_failed", profile_id=pid)
                raise RuntimeError(f"Failed to receive completion from AI Studio on profile {pid}")

            logger.info(
                "aistudio.browser.generate_content.success", profile_id=pid, length=len(final_text)
            )
            return clean_model_response(final_text)

        except Exception as e:
            curr_url = ""
            curr_title = ""
            with contextlib.suppress(Exception):
                if self.is_connected:
                    u_res, _ = await self.execute(
                        runtime.evaluate(expression="window.location.href", return_by_value=True)
                    )
                    curr_url = str(u_res.value) if u_res else ""
                    t_res, _ = await self.execute(
                        runtime.evaluate(expression="document.title", return_by_value=True)
                    )
                    curr_title = str(t_res.value) if t_res else ""

            video_file = await self.capture_error_video(reason=type(e).__name__)
            logger.warning(
                "aistudio.browser.generate_failed",
                profile_id=pid,
                error=str(e),
                current_url=curr_url,
                current_title=curr_title,
                video_path=video_file,
            )
            raise
        finally:
            self.stop_recording()
            self._is_busy = False

    async def shot(self) -> bytes:
        b64_data = await self.execute(page.capture_screenshot(format_="png"))
        return base64.b64decode(b64_data)
