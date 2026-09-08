import time
from pathlib import Path
from typing import Any

from unsafie_sdk import blobs
from unsafie_sdk.chrome import actions
from unsafie_sdk.chrome import browser as engine
from unsafie_sdk.chrome.cdp import Cdp, CdpError
from unsafie_sdk.chrome.ws import WsError
from unsafie_sdk.errors import UnsafieError
from unsafie_wire import markers

SHOTS = "shots"
STALE = (
    "closed the devtools connection",
    "stopped answering",
    "did not answer",
    "no page to drive",
    "cannot reach the browser",
)

_open: dict[str, Any] = {}


def _state() -> dict:
    state = engine.load()
    if state is None:
        raise UnsafieError("chrome is not running here", "start it: browser.start()")
    return state


def _session() -> Cdp:
    """The devtools connection of this machine, opened once and kept.

    Reconnecting per call cost three round trips (Page/Runtime/DOM.enable) on every
    goto, click and shot, and every one of them was another chance to hang.
    """
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
    """Drop the devtools connection. Safe to call from another thread."""
    cdp = _open.pop("cdp", None)
    _open.pop("port", None)
    if cdp is None:
        return
    try:
        cdp.close()
    except Exception:  # noqa: BLE001 - the point is to free the socket, not to succeed
        return


def _stale(problem: Exception) -> bool:
    text = str(problem).lower()
    return any(word in text for word in STALE)


def _act(work, *args, **kwargs) -> Any:
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            cdp = _session()
        except engine.BrowserError as broken:
            raise UnsafieError(f"cannot reach the browser: {broken}") from None
        try:
            return work(cdp, *args, **kwargs)
        except CdpError as broken:
            if attempt == 1 and _stale(broken):
                detach()
                last = broken
                continue
            raise UnsafieError(str(broken)) from None
        except (WsError, OSError) as broken:
            detach()
            if attempt == 1:
                last = broken
                continue
            raise UnsafieError(f"the browser connection broke: {broken}") from None
    raise UnsafieError(f"the browser connection broke: {last}")


def start(profile: str | None = None, *, size: str = "1920x1080", headless: bool = False) -> dict:
    """Start Chrome on this machine. A profile keeps cookies and logins between sessions."""
    if engine.load() is not None:
        return {"running": True, **_state()}
    detach()
    try:
        state = engine.launch(profile, size, headless)
    except engine.BrowserError as broken:
        raise UnsafieError(
            str(broken), "every pool machine has Chrome; on your own box install it first"
        ) from None
    engine.save(state)
    if not headless and state.get("headless"):
        print(
            "note: no X display came up, so Chrome runs headless — the desktop link will be "
            "empty. Run `unsafie-machine setup xvfb kasmvnc` on this machine."
        )
    return state


def stop(*, save_profile: bool = True) -> dict:
    """Close Chrome; the profile is stored so the next session starts logged in."""
    detach()
    state = engine.load()
    if state is None:
        return {"running": False}
    if save_profile and state.get("profile"):
        name = str(state["profile"])
        blobs.put(f"profiles/{name}.tar.gz", _pack(engine.PROFILES / name))
    engine.stop(state)
    engine.forget()
    return {"stopped": True}


def goto(url: str, *, wait: str = "load", timeout: float = 30.0) -> str:
    """Open a url and wait for it."""
    return str(_act(actions.goto, url, wait, timeout).get("url") or url)


def click(selector: str, *, button: str = "left", clicks: int = 1) -> None:
    """Click an element found by a css selector."""
    _act(actions.click, selector, button, clicks)


def type(selector: str, text: str, *, clear: bool = False) -> None:  # noqa: A001
    """Type text into a field."""
    _act(actions.type_text, selector, text, clear)


def press(combination: str) -> None:
    """Press a key or a combination: press('Enter'), press('ctrl+l')."""
    _act(actions.press, combination)


def wait(selector: str | None = None, *, url: str | None = None, js: str | None = None,
         state: str = "visible", timeout: float = 30.0) -> None:
    """Wait for an element, a url pattern or a javascript condition."""
    if selector:
        _act(actions.wait_for, selector, state, timeout)
    elif url:
        _act(actions.wait_for_url, url, timeout)
    elif js:
        _act(actions.wait_for_js, js, timeout)
    else:
        _act(actions.wait_for_load, timeout)


def text(selector: str = "body") -> str:
    """The text of an element."""
    return str(_act(actions.text_of, selector))


def html(selector: str | None = None) -> str:
    """The html of the page or of one element."""
    return str(_act(actions.html_of, selector))


def evaluate(expression: str) -> Any:
    """Run javascript in the page and return the result: evaluate("document.title")."""
    return _act(actions.evaluate, expression)


def shot(*, full: bool = False, send: bool = False, caption: str | None = None) -> str:
    """Take a screenshot. It comes back to the model as a picture; send=True also posts it.

    The marker is printed last: a call that dies after the screenshot would lose the
    picture anyway, because a failed call may only carry text back to the model.
    """
    data = _act(actions.screenshot, full)
    key = f"{SHOTS}/{int(time.time() * 1000)}.png"
    blobs.put(key, data)
    if send:
        from unsafie_sdk import chat

        chat.send_photo(data, caption=caption)
    print(markers.image(key, "image/png", caption))
    return key


def cookies(items: list[dict] | None = None) -> list[dict]:
    """Read the cookies of the page, or set them."""
    if items is None:
        return list(_act(actions.cookies))
    _act(actions.set_cookies, items)
    return items


def upload(selector: str, path: str | Path) -> None:
    """Put a file into a file input."""
    _act(actions.upload, selector, str(Path(path).resolve()))


def desktop(hold_for: float = 600.0) -> str:
    """A link to the live desktop of this machine: the human takes the mouse."""
    from unsafie_sdk import machines

    return machines.desktop(hold_for=hold_for)


def profiles() -> list[str]:
    """Profiles stored for this account."""
    rows = blobs.listing("profiles/")
    return [row["key"].removeprefix("profiles/").removesuffix(".tar.gz") for row in rows]


def restore(name: str) -> Path:
    """Bring a stored profile back onto this machine before starting Chrome."""
    import io
    import tarfile

    data = blobs.get(f"profiles/{name}.tar.gz")
    engine.PROFILES.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(engine.PROFILES, filter="data")
    return engine.PROFILES / name


def _pack(folder: Path) -> bytes:
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(folder, arcname=folder.name)
    return buffer.getvalue()
