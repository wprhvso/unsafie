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


def _state() -> dict:
    state = engine.load()
    if state is None:
        msg = "browser is not running: call unsafie browser start"
        raise RuntimeError(msg)
    return state


def _session() -> Cdp:
    state = _state()
    cached = _open.get("cdp")
    if cached is not None and _open.get("endpoint") == state.get("endpoint"):
        return cached
    detach()
    cdp, _ = engine.session(state)
    _open["cdp"] = cdp
    _open["endpoint"] = state.get("endpoint")
    _open["port"] = state.get("port")
    return cdp


def detach() -> None:
    cdp = _open.pop("cdp", None)
    _open.pop("endpoint", None)
    _open.pop("port", None)
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


def click(selector: str, *, button: str = "left", clicks: int = 1) -> dict:
    _act(actions.click, selector, button, clicks)
    return {"clicked": selector}


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
) -> dict:
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
