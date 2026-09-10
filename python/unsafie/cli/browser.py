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
        raise RuntimeError("chrome is not running: call unsafie browser start")
    return state


def _session() -> Cdp:
    state = _state()
    cached = _open.get("cdp")
    if cached is not None and _open.get("port") == state["port"]:
        return cached
    detach()
    cdp, _ = engine.session(state)
    _open["cdp"] = cdp
    _open["port"] = state["port"]
    return cdp


def detach() -> None:
    cdp = _open.pop("cdp", None)
    _open.pop("port", None)
    if cdp is not None:
        try:
            cdp.close()
        except Exception:
            pass


def _act(work, *args, **kwargs) -> Any:
    for attempt in (1, 2):
        try:
            cdp = _session()
            return work(cdp, *args, **kwargs)
        except (CdpError, WsError, OSError):
            detach()
            if attempt == 2:
                raise


def start(profile: str | None = None, *, size: str = "1920x1080", headless: bool = False) -> dict:
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


def shot(*, output: str | Path | None = None, full: bool = False) -> dict:
    data = _act(actions.screenshot, full)
    if output is not None:
        target = Path(output)
    else:
        target = Path(f"/tmp/shots/shot_{int(time.time() * 1000)}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"ok": True, "path": str(target), "bytes": len(data)}
