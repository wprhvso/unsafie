import contextlib
import time
from pathlib import Path
from typing import Any

from unsafie.chrome import actions
from unsafie.chrome import browser as engine
from unsafie.chrome.cdp import Cdp, CdpError
from unsafie.chrome.ws import WsError

SHOTS = "shots"
_open: dict[str, Any] = {}

PRESETS = {
    "images": ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.svg", "*.gif", "*.ico"],
    "fonts": ["*.woff", "*.woff2", "*.ttf", "*.otf"],
    "media": ["*.mp4", "*.webm", "*.mp3", "*.ogg"],
    "trackers": ["*google-analytics*", "*googletagmanager*", "*mc.yandex*", "*doubleclick*"],
}


def _state() -> dict:
    state = engine.load()
    if state is None:
        msg = "browser is not running: call unsafie browser start"
        raise RuntimeError(msg)
    return state


def _session() -> Cdp:
    state = _state()
    cached = _open.get("cdp")
    target_id = state.get("active_target_id")
    if (
        cached is not None
        and _open.get("endpoint") == state.get("endpoint")
        and _open.get("target_id") == target_id
    ):
        return cached
    detach()
    cdp, _ = engine.session(state)
    _open["cdp"] = cdp
    _open["endpoint"] = state.get("endpoint")
    _open["port"] = state.get("port")
    _open["target_id"] = target_id
    return cdp


def detach() -> None:
    cdp = _open.pop("cdp", None)
    _open.pop("endpoint", None)
    _open.pop("port", None)
    _open.pop("target_id", None)
    if cdp is not None:
        with contextlib.suppress(Exception):
            cdp.close()


def _act(work, *args, **kwargs) -> Any:
    for attempt in (1, 2):
        try:
            cdp = _session()
            return work(cdp, *args, **kwargs)
        except (CdpError, WsError, OSError):
            detach()
            if attempt == 2:
                raise
    return None


def start(profile: str | None = None, *, size: str = "1920x1080", headless: bool = True) -> dict:
    if engine.load() is not None:
        return {"running": True, **_state()}
    detach()
    state = engine.launch(profile, size, headless)
    engine.save(state)
    return {"running": True, **state}


def stop() -> dict:
    detach()
    state = engine.load()
    if state is None:
        return {"running": False}
    engine.stop(state)
    engine.forget()
    return {"stopped": True}


def goto(url: str, *, wait: str = "load", timeout: float = 30.0) -> dict:
    return _act(actions.goto, url, wait, timeout)


def back(timeout: float = 30.0) -> dict:
    return _act(actions.back, timeout)


def forward(timeout: float = 30.0) -> dict:
    return _act(actions.forward, timeout)


def reload(ignore_cache: bool = False, timeout: float = 30.0) -> dict:
    return _act(actions.reload_page, ignore_cache, timeout)


def url() -> dict:
    return {"url": _act(actions.current_url)}


def title() -> dict:
    return {"title": _act(actions.title_of)}


def click(selector: str, *, button: str = "left", clicks: int = 1) -> dict:
    _act(actions.click, selector, button, clicks)
    return {"clicked": selector}


def hover(selector: str) -> dict:
    coords = _act(actions.hover, selector)
    return {"hovered": selector, "coords": {"x": coords[0], "y": coords[1]}}


def drag(from_selector: str, to_selector: str, *, steps: int = 5) -> dict:
    _act(actions.drag, from_selector, to_selector, steps)
    return {"dragged": True, "from": from_selector, "to": to_selector}


def type_text(selector: str, text: str, *, clear: bool = False) -> dict:
    _act(actions.type_text, selector, text, clear)
    return {"typed": selector}


def press(combination: str) -> dict:
    _act(actions.press, combination)
    return {"pressed": combination}


def wait(
    selector: str | None = None,
    *,
    url: str | None = None,
    js: str | None = None,
    state: str = "visible",
    timeout: float = 30.0,
    network_idle: bool = False,
    idle_time: float = 0.5,
) -> dict:
    if network_idle:
        elapsed = _act(actions.wait_for_network_idle, idle_time, timeout)
        return {"waited": True, "condition": "network-idle", "elapsed_s": elapsed}
    if selector:
        _act(actions.wait_for, selector, state, timeout)
    elif url:
        _act(actions.wait_for_url, url, timeout)
    elif js:
        _act(actions.wait_for_js, js, timeout)
    else:
        _act(actions.wait_for_load, timeout)
    return {"waited": True}


def text(selector: str = "body") -> dict:
    return {"text": _act(actions.text_of, selector)}


def html(selector: str | None = None) -> dict:
    return {"html": _act(actions.html_of, selector)}


def query(selector: str, limit: int = 20) -> dict:
    items = _act(actions.query_elements, selector, limit)
    return {"selector": selector, "count": len(items), "items": items}


def scroll(
    by: str | None = None,
    to: str | None = None,
    *,
    top: bool = False,
    bottom: bool = False,
) -> dict:
    return _act(actions.scroll, by, to, top, bottom)


def evaluate(expression: str) -> dict:
    return {"result": _act(actions.evaluate, expression)}


def shot(*, output: str | Path | None = None, full: bool = False) -> dict:
    data = _act(actions.screenshot, full)
    if output is not None:
        target = Path(output)
        if target.is_dir():
            target = target / f"shot_{int(time.time() * 1000)}.png"
    else:
        target = Path(f"/tmp/shots/shot_{int(time.time() * 1000)}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"ok": True, "path": str(target), "bytes": len(data)}


def cookies(items: list[dict] | None = None) -> dict:
    if items is None:
        return {"cookies": _act(actions.cookies)}
    _act(actions.set_cookies, items)
    return {"cookies": items}


def upload(selector: str, path: str) -> dict:
    target = Path(path).resolve()
    if not target.is_file():
        msg = f"file not found: {path}"
        raise FileNotFoundError(msg)
    _act(actions.upload, selector, str(target))
    return {"uploaded": selector, "path": str(target), "bytes": target.stat().st_size}


def network(pattern: str | None = None, limit: int = 50, *, clear: bool = False) -> dict:
    return _act(actions.network_log, pattern, limit, clear)


def block(
    patterns: list[str] | None = None, presets: str | None = None, *, clear: bool = False
) -> dict:
    state = _state()
    active_patterns = set() if clear else set(state.get("blocked_patterns") or [])
    if presets:
        for p in presets.split(","):
            p = p.strip().lower()
            if p in PRESETS:
                active_patterns.update(PRESETS[p])
    if patterns:
        for pat in patterns:
            if pat.lower() in PRESETS:
                active_patterns.update(PRESETS[pat.lower()])
            else:
                active_patterns.add(pat)
    sorted_patterns = sorted(active_patterns)
    state["blocked_patterns"] = sorted_patterns
    engine.save(state)
    _act(actions.set_blocked_urls, sorted_patterns)
    return {"blocked_patterns": sorted_patterns}


def tabs() -> dict:
    state = _state()
    items = _act(actions.list_tabs)
    active = state.get("active_target_id")
    if not active and items:
        active = items[0]["id"]
    return {"active": active, "tabs": items}


def tab_new(url: str | None = None) -> dict:
    tid = _act(actions.new_tab, url)
    return tab_switch(tid)


def tab_switch(target_id: str) -> dict:
    state = _state()
    _act(actions.switch_tab, target_id)
    state["active_target_id"] = target_id
    engine.save(state)
    detach()
    return {"active": target_id, "url": _act(actions.current_url), "title": _act(actions.title_of)}


def tab_close(target_id: str | None = None) -> dict:
    state = _state()
    tid = target_id or state.get("active_target_id")
    if not tid:
        items = _act(actions.list_tabs)
        if items:
            tid = items[0]["id"]
    if tid:
        _act(actions.close_tab, tid)
    if state.get("active_target_id") == tid:
        state.pop("active_target_id", None)
        engine.save(state)
        detach()
    remaining = _act(actions.list_tabs)
    return {"closed": tid, "remaining": len(remaining)}


def frame(
    selector_or_id: str | None = None, *, main: bool = False, list_frames: bool = False
) -> dict:
    state = _state()
    if list_frames:
        return {"frames": _act(actions.frame_tree)}
    if main:
        state.pop("active_frame_id", None)
        engine.save(state)
        return {"active_frame": "main"}
    if not selector_or_id:
        return {"active_frame": state.get("active_frame_id", "main")}
    tree = _act(actions.frame_tree)
    if selector_or_id in [f["id"] for f in tree]:
        fid = selector_or_id
    else:
        fid = _act(actions.find_frame_id, selector_or_id)
    state["active_frame_id"] = fid
    engine.save(state)
    return {"active_frame": fid}


def console(level: str | None = None, limit: int = 50, *, clear: bool = False) -> dict:
    return _act(actions.console_logs, level, limit, clear)


def intercept(
    pattern: str,
    *,
    block: bool = True,
    click_selector: str | None = None,
    timeout: float = 30.0,
) -> dict:
    return _act(actions.intercept_request, pattern, block, click_selector, timeout)
