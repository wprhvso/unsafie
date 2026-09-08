import time
from pathlib import Path
from typing import Any

from unsafie_sdk import store
from unsafie_sdk.chrome import actions
from unsafie_sdk.chrome import browser as engine
from unsafie_sdk.chrome.cdp import CdpError
from unsafie_sdk.errors import UnsafieError
from unsafie_wire import markers

SHOTS = "shots"


def _state() -> dict:
    state = engine.load()
    if state is None:
        raise UnsafieError("chrome is not running here", "start it: browser.start()")
    return state


def _session():
    return engine.session(_state())


def _act(work, *args, **kwargs) -> Any:
    cdp, _ = _session()
    try:
        return work(cdp, *args, **kwargs)
    except CdpError as broken:
        raise UnsafieError(str(broken)) from None
    finally:
        cdp.close()


def start(profile: str | None = None, *, size: str = "1920x1080", headless: bool = False) -> dict:
    """Start Chrome on this machine. A profile keeps cookies and logins between sessions."""
    if engine.load() is not None:
        return {"running": True, **_state()}
    try:
        state = engine.launch(profile, size, headless)
    except engine.BrowserError as broken:
        raise UnsafieError(
            str(broken), "every pool machine has Chrome; on your own box install it first"
        ) from None
    engine.save(state)
    return state


def stop(*, save_profile: bool = True) -> dict:
    """Close Chrome; the profile is stored so the next session starts logged in."""
    state = engine.load()
    if state is None:
        return {"running": False}
    if save_profile and state.get("profile"):
        name = str(state["profile"])
        store.put(f"profiles/{name}.tar.gz", _pack(engine.PROFILES / name))
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
    """Take a screenshot. It comes back to the model as a picture; send=True also posts it."""
    data = _act(actions.screenshot, full)
    key = f"{SHOTS}/{int(time.time() * 1000)}.png"
    store.put(key, data)
    print(markers.image(key, "image/png", caption))
    if send:
        from unsafie_sdk import chat

        chat.photo(data, caption=caption)
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


def desktop() -> str:
    """A link to the live desktop of this machine: the human takes the mouse."""
    from unsafie_sdk import machines

    return machines.desktop()


def profiles() -> list[str]:
    """Profiles stored for this account."""
    rows = store.listing("profiles/")
    return [row["key"].removeprefix("profiles/").removesuffix(".tar.gz") for row in rows]


def restore(name: str) -> Path:
    """Bring a stored profile back onto this machine before starting Chrome."""
    import io
    import tarfile

    data = store.get(f"profiles/{name}.tar.gz")
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
