import json
import time
from typing import Any

from unsafie_sdk.chrome.cdp import Cdp, CdpError

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
        raise CdpError(f"{url}: {answer['errorText']}")
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
    raise CdpError(f"the page did not finish loading in {timeout:.0f}s")


def current_url(cdp: Cdp) -> str:
    return str(evaluate(cdp, "location.href") or "")


def title(cdp: Cdp) -> str:
    return str(evaluate(cdp, "document.title") or "")


def _quote(value: str) -> str:
    return json.dumps(value)


def find(cdp: Cdp, selector: str) -> bool:
    return bool(evaluate(cdp, f"!!document.querySelector({_quote(selector)})"))


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
        raise CdpError("state must be visible, hidden, attached or detached")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if evaluate(cdp, check):
            return
        time.sleep(POLL)
    raise CdpError(f"{selector} is not {state} after {timeout:.0f}s")


def wait_for_url(cdp: Cdp, pattern: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pattern in current_url(cdp):
            return
        time.sleep(POLL)
    raise CdpError(f"the url did not become {pattern} in {timeout:.0f}s")


def wait_for_js(cdp: Cdp, expression: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if evaluate(cdp, expression):
                return
        except CdpError:
            pass
        time.sleep(POLL)
    raise CdpError(f"the condition stayed false for {timeout:.0f}s")


def centre(cdp: Cdp, selector: str) -> tuple[float, float]:
    box = evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        " if (!e) return null; e.scrollIntoView({block: 'center', inline: 'center'});"
        " const r = e.getBoundingClientRect();"
        " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()",
    )
    if not box:
        raise CdpError(f"no element matches {selector}")
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


def hover(cdp: Cdp, selector: str) -> None:
    x, y = centre(cdp, selector)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})


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
        raise CdpError(f"no element matches {selector}")
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
            raise CdpError(f"unknown key '{key}'")
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


def select(cdp: Cdp, selector: str, value: str) -> None:
    done = evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        f" if (!e) return false; e.value = {_quote(value)};"
        " e.dispatchEvent(new Event('change', {bubbles: true})); return true; }})()",
    )
    if not done:
        raise CdpError(f"no element matches {selector}")


def scroll(cdp: Cdp, selector: str | None, by: int | None) -> None:
    if selector:
        evaluate(
            cdp,
            f"(() => {{ const e = document.querySelector({_quote(selector)});"
            " if (e) e.scrollIntoView({block: 'center'}); })()",
        )
        return
    evaluate(cdp, f"window.scrollBy(0, {int(by or 400)})")


def text_of(cdp: Cdp, selector: str) -> str:
    value = evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        " return e ? e.innerText : null; })()",
    )
    if value is None:
        raise CdpError(f"no element matches {selector}")
    return str(value)


def html_of(cdp: Cdp, selector: str | None) -> str:
    if selector:
        value = evaluate(
            cdp,
            f"(() => {{ const e = document.querySelector({_quote(selector)});"
            " return e ? e.outerHTML : null; })()",
        )
        if value is None:
            raise CdpError(f"no element matches {selector}")
        return str(value)
    return str(evaluate(cdp, "document.documentElement.outerHTML") or "")


def attribute(cdp: Cdp, selector: str, name: str) -> str | None:
    return evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        f" return e ? e.getAttribute({_quote(name)}) : null; }})()",
    )


def value_of(cdp: Cdp, selector: str) -> str:
    value = evaluate(
        cdp,
        f"(() => {{ const e = document.querySelector({_quote(selector)});"
        " return e ? e.value : null; })()",
    )
    if value is None:
        raise CdpError(f"no element matches {selector}")
    return str(value)


def screenshot(cdp: Cdp, full: bool = False) -> bytes:
    import base64

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


def upload(cdp: Cdp, selector: str, path: str) -> None:
    document = cdp.call("DOM.getDocument", {"depth": 0})
    node = cdp.call(
        "DOM.querySelector",
        {"nodeId": document["root"]["nodeId"], "selector": selector},
    )
    if not node.get("nodeId"):
        raise CdpError(f"no element matches {selector}")
    cdp.call("DOM.setFileInputFiles", {"files": [path], "nodeId": node["nodeId"]})
