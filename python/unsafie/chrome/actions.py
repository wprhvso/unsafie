import base64
import contextlib
import json
import time
from typing import Any

from unsafie.chrome.cdp import Cdp, CdpError

READY = "document.readyState === 'complete'"
POLL = 0.2


def evaluate(cdp: Cdp, expression: str, await_promise: bool = False) -> Any:
    answer = cdp.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
            "userGesture": True,
        },
    )
    if answer.get("exceptionDetails"):
        detail = answer["exceptionDetails"]
        text = detail.get("exception", {}).get("description") or detail.get("text")
        raise CdpError(str(text))
    return answer.get("result", {}).get("value")


def goto(cdp: Cdp, url: str, wait: str = "load", timeout: float = 30.0) -> dict:
    answer = cdp.call("Page.navigate", {"url": url})
    if answer.get("errorText"):
        msg = f"{url}: {answer['errorText']}"
        raise CdpError(msg)
    if wait != "none":
        wait_for_load(cdp, timeout)
    return {"url": current_url(cdp), "frame": answer.get("frameId")}


def wait_for_load(cdp: Cdp, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if evaluate(cdp, READY):
                return
        except CdpError:
            pass
        time.sleep(POLL)
    msg = f"the page did not finish loading in {timeout:.0f}s"
    raise CdpError(msg)


def current_url(cdp: Cdp) -> str:
    return str(evaluate(cdp, "location.href") or "")


def title_of(cdp: Cdp) -> str:
    return str(evaluate(cdp, "document.title") or "")


def _quote(value: str) -> str:
    return json.dumps(value)


def wait_for(cdp: Cdp, selector: str, state: str = "visible", timeout: float = 30.0) -> None:
    check = {
        "visible": (
            f"(() => {{ const e = document.querySelector({_quote(selector)});"
            " if (!e) return false; const r = e.getBoundingClientRect();"
            " return r.width > 0 && r.height > 0; }})()"
        ),
        "hidden": (
            f"(() => {{ const e = document.querySelector({_quote(selector)});"
            " if (!e) return true; const r = e.getBoundingClientRect();"
            " return r.width === 0 || r.height === 0; }})()"
        ),
        "attached": f"!!document.querySelector({_quote(selector)})",
        "detached": f"!document.querySelector({_quote(selector)})",
    }.get(state)
    if check is None:
        msg = "state must be visible, hidden, attached or detached"
        raise CdpError(msg)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if evaluate(cdp, check):
            return
        time.sleep(POLL)
    msg = f"{selector} is not {state} after {timeout:.0f}s"
    raise CdpError(msg)


def wait_for_url(cdp: Cdp, pattern: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pattern in current_url(cdp):
            return
        time.sleep(POLL)
    msg = f"the url did not become {pattern} in {timeout:.0f}s"
    raise CdpError(msg)


def wait_for_js(cdp: Cdp, expression: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if evaluate(cdp, expression):
                return
        except CdpError:
            pass
        time.sleep(POLL)
    msg = f"the condition stayed false for {timeout:.0f}s"
    raise CdpError(msg)


def wait_for_network_idle(cdp: Cdp, idle_time: float = 0.5, timeout: float = 30.0) -> float:
    start = time.monotonic()
    deadline = start + timeout
    last_count = -1
    quiet_since = time.monotonic()
    script = "window.performance.getEntriesByType('resource').length"
    while time.monotonic() < deadline:
        try:
            count = int(evaluate(cdp, script) or 0)
        except CdpError:
            count = -1
        if count != last_count:
            last_count = count
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= idle_time:
            return round(time.monotonic() - start, 2)
        time.sleep(POLL)
    msg = f"network did not become idle in {timeout:.0f}s"
    raise CdpError(msg)


def centre(cdp: Cdp, selector: str) -> tuple[float, float]:
    box = evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        " if (!e) return null; e.scrollIntoView({block: 'center', inline: 'center'});"
        " const r = e.getBoundingClientRect();"
        " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()",
    )
    if not box:
        msg = f"no element matches {selector}"
        raise CdpError(msg)
    return float(box["x"]), float(box["y"])


def click(cdp: Cdp, selector: str, button: str = "left", clicks: int = 1) -> None:
    x, y = centre(cdp, selector)
    for event in ("mouseMoved", "mousePressed", "mouseReleased"):
        cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": event,
                "x": x,
                "y": y,
                "button": button,
                "clickCount": clicks if event != "mouseMoved" else 0,
                "buttons": 1 if button == "left" else 2,
            },
        )


def hover(cdp: Cdp, selector: str) -> tuple[float, float]:
    x, y = centre(cdp, selector)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    return x, y


def drag(cdp: Cdp, from_selector: str, to_selector: str, steps: int = 5) -> None:
    x1, y1 = centre(cdp, from_selector)
    x2, y2 = centre(cdp, to_selector)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x1, "y": y1})
    cdp.call(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1, "buttons": 1},
    )
    step_count = max(1, steps)
    for i in range(1, step_count + 1):
        xi = x1 + (x2 - x1) * (i / step_count)
        yi = y1 + (y2 - y1) * (i / step_count)
        cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": xi, "y": yi, "buttons": 1})
        time.sleep(0.015)
    cdp.call(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": x2,
            "y": y2,
            "button": "left",
            "clickCount": 1,
            "buttons": 0,
        },
    )


def scroll(
    cdp: Cdp,
    by: str | None = None,
    to: str | None = None,
    top: bool = False,
    bottom: bool = False,
) -> dict:
    if to:
        found = evaluate(
            cdp,
            f"(() => {{ const e = document.querySelector({_quote(to)});"
            " if (!e) return false; e.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'}); return true; })()",
        )
        if not found:
            msg = f"no element matches {to}"
            raise CdpError(msg)
    elif top:
        evaluate(cdp, "window.scrollTo({top: 0, left: 0, behavior: 'instant'})")
    elif bottom:
        evaluate(
            cdp,
            "window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})",
        )
    elif by:
        parts = [float(p.strip()) for p in by.split(",") if p.strip()]
        dx = parts[0] if len(parts) > 0 else 0.0
        dy = parts[1] if len(parts) > 1 else 0.0
        cdp.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": 100, "y": 100, "deltaX": dx, "deltaY": dy},
        )
    info = (
        evaluate(
            cdp,
            "({x: window.scrollX, y: window.scrollY, maxX: document.documentElement.scrollWidth, maxY: document.documentElement.scrollHeight})",
        )
        or {}
    )
    return {
        "scrolled": True,
        "scroll_x": info.get("x", 0),
        "scroll_y": info.get("y", 0),
        "max_scroll_y": info.get("maxY", 0),
    }


def query_elements(cdp: Cdp, selector: str, limit: int = 20) -> list[dict]:
    script = (
        f"(() => {{ const els = Array.from(document.querySelectorAll({_quote(selector)})).slice(0, {limit});"
        " return els.map((el, i) => {"
        " const r = el.getBoundingClientRect();"
        " const attrs = {};"
        " for (const a of el.attributes) attrs[a.name] = a.value;"
        " const s = window.getComputedStyle(el);"
        " const v = r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';"
        " return {"
        "   index: i, tag: el.tagName.toLowerCase(),"
        "   text: (el.innerText || el.value || '').trim().slice(0, 200),"
        "   visible: v,"
        "   rect: {x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height)},"
        "   attributes: attrs"
        " }; }); })()"
    )
    result = evaluate(cdp, script)
    return list(result or [])


def type_text(cdp: Cdp, selector: str, text: str, clear: bool = False) -> None:
    wipe = "e.value = '';" if clear else ""
    focus = (
        "(() => { const e = document.querySelector("
        + _quote(selector)
        + "); if (!e) return false; e.focus(); "
        + wipe
        + " return true; })()"
    )
    if not evaluate(cdp, focus):
        msg = f"no element matches {selector}"
        raise CdpError(msg)
    for character in text:
        cdp.call("Input.insertText", {"text": character})
    evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        " if (e) { e.dispatchEvent(new Event('input', {bubbles: true}));"
        " e.dispatchEvent(new Event('change', {bubbles: true})); } })()",
    )


KEYS = {
    "enter": ("Enter", "\r", 13),
    "tab": ("Tab", "\t", 9),
    "escape": ("Escape", "", 27),
    "backspace": ("Backspace", "", 8),
    "delete": ("Delete", "", 46),
    "arrowup": ("ArrowUp", "", 38),
    "arrowdown": ("ArrowDown", "", 40),
    "arrowleft": ("ArrowLeft", "", 37),
    "arrowright": ("ArrowRight", "", 39),
    "home": ("Home", "", 36),
    "end": ("End", "", 35),
    "pageup": ("PageUp", "", 33),
    "pagedown": ("PageDown", "", 34),
    "space": (" ", " ", 32),
}
MODIFIERS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "cmd": 4, "shift": 8}


def press(cdp: Cdp, combination: str) -> None:
    pieces = [piece.strip().lower() for piece in combination.split("+") if piece.strip()]
    modifiers = 0
    key = ""
    for piece in pieces:
        if piece in MODIFIERS:
            modifiers |= MODIFIERS[piece]
        else:
            key = piece
    named = KEYS.get(key)
    if named is None:
        if len(key) != 1:
            msg = f"unknown key '{key}'"
            raise CdpError(msg)
        named = (key.upper() if len(key) == 1 else key, key, ord(key.upper()))
    identifier, text, code = named
    for event in ("keyDown", "keyUp"):
        cdp.call(
            "Input.dispatchKeyEvent",
            {
                "type": event,
                "key": identifier,
                "text": text if event == "keyDown" and not modifiers else "",
                "windowsVirtualKeyCode": code,
                "nativeVirtualKeyCode": code,
                "modifiers": modifiers,
            },
        )


def back(cdp: Cdp, timeout: float = 30.0) -> dict:
    hist = cdp.call("Page.getNavigationHistory")
    idx = hist.get("currentIndex", 0)
    entries = hist.get("entries", [])
    if idx <= 0:
        msg = "no back history available"
        raise CdpError(msg)
    target = entries[idx - 1]
    cdp.call("Page.navigateToHistoryEntry", {"entryId": target["id"]})
    wait_for_load(cdp, timeout)
    return {"navigated": "back", "url": current_url(cdp), "entry_id": target["id"]}


def forward(cdp: Cdp, timeout: float = 30.0) -> dict:
    hist = cdp.call("Page.getNavigationHistory")
    idx = hist.get("currentIndex", 0)
    entries = hist.get("entries", [])
    if idx >= len(entries) - 1:
        msg = "no forward history available"
        raise CdpError(msg)
    target = entries[idx + 1]
    cdp.call("Page.navigateToHistoryEntry", {"entryId": target["id"]})
    wait_for_load(cdp, timeout)
    return {"navigated": "forward", "url": current_url(cdp), "entry_id": target["id"]}


def reload_page(cdp: Cdp, ignore_cache: bool = False, timeout: float = 30.0) -> dict:
    cdp.call("Page.reload", {"ignoreCache": ignore_cache})
    wait_for_load(cdp, timeout)
    return {"reloaded": True, "url": current_url(cdp), "ignore_cache": ignore_cache}


def text_of(cdp: Cdp, selector: str) -> str:
    value = evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        " return e ? e.innerText : null; })()",
    )
    if value is None:
        msg = f"no element matches {selector}"
        raise CdpError(msg)
    return str(value)


def html_of(cdp: Cdp, selector: str | None) -> str:
    if selector:
        value = evaluate(
            cdp,
            f"(() => {{ const e = document.querySelector({_quote(selector)});"
            " return e ? e.outerHTML : null; })()",
        )
        if value is None:
            msg = f"no element matches {selector}"
            raise CdpError(msg)
        return str(value)
    return str(evaluate(cdp, "document.documentElement.outerHTML") or "")


def screenshot(cdp: Cdp, full: bool = False) -> bytes:
    params: dict[str, Any] = {"format": "png"}
    if full:
        params["captureBeyondViewport"] = True
    answer = cdp.call("Page.captureScreenshot", params)
    return base64.b64decode(answer.get("data") or "")


def cookies(cdp: Cdp) -> list[dict]:
    answer = cdp.call("Network.getCookies")
    return list(answer.get("cookies") or [])


def set_cookies(cdp: Cdp, items: list[dict]) -> None:
    cdp.call("Network.setCookies", {"cookies": items})


def set_blocked_urls(cdp: Cdp, urls: list[str]) -> None:
    cdp.call("Network.enable")
    cdp.call("Network.setBlockedURLs", {"urls": urls})


def network_log(
    cdp: Cdp,
    pattern: str | None = None,
    limit: int = 50,
    clear: bool = False,
) -> dict:
    if clear:
        evaluate(cdp, "window.performance.clearResourceTimings()")
        return {"count": 0, "requests": [], "cleared": True}
    script = (
        "(() => {"
        " const entries = window.performance.getEntriesByType('resource');"
        " return entries.map(e => ({"
        "   name: e.name, type: e.initiatorType, duration: Math.round(e.duration),"
        "   size: e.transferSize || 0, start: Math.round(e.startTime)"
        " })); })()"
    )
    raw = evaluate(cdp, script) or []
    if pattern:
        raw = [r for r in raw if pattern in r.get("name", "")]
    items = raw[-limit:]
    return {"count": len(items), "requests": items}


def console_logs(
    cdp: Cdp,
    level: str | None = None,
    limit: int = 50,
    clear: bool = False,
) -> dict:
    if clear:
        evaluate(cdp, "window.__unsafie_logs = []")
        return {"count": 0, "messages": [], "cleared": True}
    script = "(() => { if (!window.__unsafie_logs) return []; return window.__unsafie_logs;})()"
    logs = list(evaluate(cdp, script) or [])
    if level and level != "all":
        logs = [item for item in logs if item.get("level") == level]
    return {"count": len(logs[-limit:]), "messages": logs[-limit:]}


def list_tabs(cdp: Cdp) -> list[dict]:
    targets = cdp.call("Target.getTargets")
    items = []
    for t in targets.get("targetInfos", []):
        if t.get("type") == "page":
            items.append(
                {
                    "id": t["targetId"],
                    "title": t.get("title", ""),
                    "url": t.get("url", ""),
                }
            )
    return items


def new_tab(cdp: Cdp, url: str | None = None) -> str:
    res = cdp.call("Target.createTarget", {"url": url or "about:blank"})
    return str(res.get("targetId") or "")


def switch_tab(cdp: Cdp, target_id: str) -> None:
    cdp.call("Target.activateTarget", {"targetId": target_id})


def close_tab(cdp: Cdp, target_id: str) -> None:
    cdp.call("Target.closeTarget", {"targetId": target_id})


def frame_tree(cdp: Cdp) -> list[dict]:
    tree = cdp.call("Page.getFrameTree")
    frames = []

    def walk(node: dict) -> None:
        f = node.get("frame", {})
        frames.append({"id": f.get("id"), "url": f.get("url", ""), "name": f.get("name", "")})
        for ch in node.get("childFrames", []):
            walk(ch)

    walk(tree.get("frameTree", {}))
    return frames


def find_frame_id(cdp: Cdp, selector: str) -> str:
    doc = cdp.call("DOM.getDocument", {"depth": 0})
    node = cdp.call("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": selector})
    if not node.get("nodeId"):
        msg = f"no iframe matches {selector}"
        raise CdpError(msg)
    desc = cdp.call("DOM.describeNode", {"nodeId": node["nodeId"]})
    fid = desc.get("node", {}).get("frameId")
    if not fid:
        msg = f"element {selector} is not a valid frame"
        raise CdpError(msg)
    return str(fid)


def intercept_request(
    cdp: Cdp,
    pattern: str,
    block: bool = True,
    click_selector: str | None = None,
    timeout: float = 30.0,
) -> dict:
    cdp.call(
        "Fetch.enable",
        {"patterns": [{"urlPattern": pattern, "requestStage": "Request"}]},
    )
    try:
        if click_selector:
            click(cdp, click_selector)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cdp.drain(0.1)
            events = cdp.events("Fetch.requestPaused")
            if events:
                ev = events[-1]
                params = ev.get("params", ev)
                req_id = params.get("requestId") or ev.get("requestId", "")
                req = params.get("request") or ev.get("request", {})
                url = req.get("url", "")
                method = req.get("method", "GET")
                headers = req.get("headers", {})
                body = req.get("postData")
                if req.get("hasPostData") and not body:
                    with contextlib.suppress(Exception):
                        post_res = cdp.call("Fetch.getRequestPostData", {"requestId": req_id})
                        body = post_res.get("postData")
                body_json = None
                if body:
                    with contextlib.suppress(Exception):
                        body_json = json.loads(body)
                target_session = ev.get("sessionId") or cdp.session_id
                if block:
                    cdp.call(
                        "Fetch.failRequest",
                        {"requestId": req_id, "errorReason": "BlockedByClient"},
                        session=target_session,
                    )
                else:
                    cdp.call("Fetch.continueRequest", {"requestId": req_id}, session=target_session)
                return {
                    "intercepted": True,
                    "url": url,
                    "method": method,
                    "blocked": block,
                    "headers": headers,
                    "body": body,
                    "body_json": body_json,
                }
            time.sleep(POLL)
        msg = f"no request matched {pattern} within {timeout:.0f}s"
        raise CdpError(msg)
    finally:
        with contextlib.suppress(Exception):
            cdp.call("Fetch.disable")


def upload(cdp: Cdp, selector: str, path: str) -> None:
    document = cdp.call("DOM.getDocument", {"depth": 0})
    node = cdp.call(
        "DOM.querySelector",
        {"nodeId": document["root"]["nodeId"], "selector": selector},
    )
    if not node.get("nodeId"):
        msg = f"no element matches {selector}"
        raise CdpError(msg)
    cdp.call("DOM.setFileInputFiles", {"files": [path], "nodeId": node["nodeId"]})
    evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        " if (e) { e.dispatchEvent(new Event('input', {bubbles: true}));"
        " e.dispatchEvent(new Event('change', {bubbles: true})); } })()",
    )
