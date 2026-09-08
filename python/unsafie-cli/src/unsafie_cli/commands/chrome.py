import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
from pathlib import Path

from unsafie_cli import api
from unsafie_cli.chrome import actions, browser
from unsafie_cli.chrome.cdp import CdpError
from unsafie_cli.errors import FAILED, NOT_FOUND, OK, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call
from unsafie_wire import markers

SHOT_PREFIX = "shots"


def _state(call: Call) -> dict:
    state = browser.load()
    if state is None:
        raise CliError(
            "chrome is not running here",
            NOT_FOUND,
            "start it: unsafie chrome start [--profile name]",
        )
    return state


def _open(call: Call):
    return browser.session(_state(call))


def start(call: Call, out: Out) -> int:
    if browser.load() is not None:
        out.send({"running": True}, ["chrome is already running"])
        return OK
    try:
        state = browser.launch(
            call.flag("profile") or None,
            call.flag("size") or "1920x1080",
            call.on("headless"),
        )
    except browser.BrowserError as broken:
        raise CliError(str(broken), FAILED) from None
    browser.save(state)
    out.send(
        state,
        [
            f"chrome up on port {state['port']}"
            + (f", profile {state['profile']}" if state["profile"] else ", scratch profile")
            + (" (headless)" if state["headless"] else f" on {state['display']}")
        ],
    )
    return OK


def stop(call: Call, out: Out) -> int:
    state = browser.load()
    if state is None:
        out.send({"running": False}, ["chrome was not running"])
        return OK
    if call.on("save-profile") and state.get("profile"):
        name = str(state["profile"])
        key = f"profiles/{name}.tar.gz"
        api.client(call).raw(
            "PUT", f"/blobs/{urllib.parse.quote(key)}", _pack(browser.PROFILES / name)
        )
        out.line(f"profile {name} stored as {key}")
    browser.stop(state)
    browser.forget()
    out.send({"stopped": True}, ["chrome stopped"])
    return OK


def status(call: Call, out: Out) -> int:
    state = browser.load()
    if state is None:
        out.send({"running": False}, ["chrome is not running"])
        return OK
    try:
        cdp, _ = browser.session(state)
        url = actions.current_url(cdp)
        name = actions.title(cdp)
        cdp.close()
    except (browser.BrowserError, CdpError) as broken:
        url, name = "-", f"({broken})"
    answer = {**state, "url": url, "title": name, "uptime": round(time.time() - state["started_at"])}
    if out.json_mode:
        out.send(answer)
        return OK
    out.table(
        [
            ("profile", state.get("profile") or "scratch"),
            ("mode", "headless" if state.get("headless") else state.get("display", "")),
            ("url", url),
            ("title", name),
            ("uptime", f"{answer['uptime']}s"),
        ]
    )
    return OK


def goto(call: Call, out: Out) -> int:
    cdp, _ = _open(call)
    try:
        answer = actions.goto(
            cdp,
            call.arg("url"),
            call.flag("wait") or "load",
            float(call.flag("timeout") or "30"),
        )
    finally:
        cdp.close()
    out.send(answer, [answer["url"]])
    return OK


def _simple(call: Call, out: Out, run) -> int:
    cdp, _ = _open(call)
    try:
        answer = run(cdp)
    except CdpError as broken:
        cdp.close()
        raise CliError(str(broken), FAILED) from None
    cdp.close()
    if answer is None:
        out.send({"ok": True}, ["done"])
    elif isinstance(answer, (dict, list)):
        out.send(answer, [json.dumps(answer, ensure_ascii=False)])
    else:
        out.send({"value": answer}, [str(answer)])
    return OK


def back(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.evaluate(cdp, "history.back()"))


def forward(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.evaluate(cdp, "history.forward()"))


def reload(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: cdp.call("Page.reload", {}) and None)


def click(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.click(cdp, call.arg("selector")))


def dblclick(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.click(cdp, call.arg("selector"), clicks=2))


def rclick(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.click(cdp, call.arg("selector"), button="right"))


def hover(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.hover(cdp, call.arg("selector")))


def type_text(call: Call, out: Out) -> int:
    return _simple(
        call,
        out,
        lambda cdp: actions.type_text(cdp, call.arg("selector"), call.arg("text"), call.on("clear")),
    )


def press(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.press(cdp, call.arg("key")))


def hotkey(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.press(cdp, call.arg("keys")))


def select(call: Call, out: Out) -> int:
    return _simple(
        call, out, lambda cdp: actions.select(cdp, call.arg("selector"), call.arg("value"))
    )


def scroll(call: Call, out: Out) -> int:
    by = int(call.flag("by")) if call.flag("by") else None
    return _simple(call, out, lambda cdp: actions.scroll(cdp, call.arg("selector") or None, by))


def wait(call: Call, out: Out) -> int:
    timeout = float(call.flag("timeout") or "30")

    def run(cdp):
        if call.flag("url"):
            return actions.wait_for_url(cdp, call.flag("url"), timeout)
        if call.flag("js"):
            return actions.wait_for_js(cdp, call.flag("js"), timeout)
        if call.arg("selector"):
            return actions.wait_for(cdp, call.arg("selector"), call.flag("state") or "visible", timeout)
        return actions.wait_for_load(cdp, timeout)

    return _simple(call, out, run)


def text(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.text_of(cdp, call.arg("selector")))


def html(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.html_of(cdp, call.arg("selector") or None))


def attr(call: Call, out: Out) -> int:
    return _simple(
        call, out, lambda cdp: actions.attribute(cdp, call.arg("selector"), call.arg("name"))
    )


def value(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.value_of(cdp, call.arg("selector")))


def url(call: Call, out: Out) -> int:
    return _simple(call, out, actions.current_url)


def title(call: Call, out: Out) -> int:
    return _simple(call, out, actions.title)


def evaluate(call: Call, out: Out) -> int:
    return _simple(call, out, lambda cdp: actions.evaluate(cdp, call.arg("expression"), True))


def script(call: Call, out: Out) -> int:
    path = Path(call.arg("file"))
    if not path.is_file():
        raise CliError(f"no file at {path}", NOT_FOUND)
    body = path.read_text(encoding="utf-8")
    if call.on("on-load"):
        return _simple(
            call,
            out,
            lambda cdp: cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": body}),
        )
    return _simple(call, out, lambda cdp: actions.evaluate(cdp, body, True))


def markdown(call: Call, out: Out) -> int:
    cdp, _ = _open(call)
    try:
        body = actions.html_of(cdp, call.arg("selector") or None)
    finally:
        cdp.close()
    out.line(_to_markdown(body))
    return OK


def _converter():
    import importlib

    for module, attribute in (("bloat2md", "to_markdown"), ("llmmd", "html_to_markdown")):
        try:
            found = getattr(importlib.import_module(module), attribute, None)
        except ImportError:
            continue
        if callable(found):
            return found
    return None


def _to_markdown(body: str) -> str:
    convert = _converter()
    if convert is None:
        return _strip(body)
    try:
        return str(convert(body))
    except Exception:
        return _strip(body)


def _strip(body: str) -> str:
    import re

    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return re.sub(r"[ \t]*\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", body)).strip()


def shot(call: Call, out: Out) -> int:
    cdp, _ = _open(call)
    try:
        data = actions.screenshot(cdp, call.on("full"))
    finally:
        cdp.close()
    target = call.flag("out")
    if target:
        Path(target).write_bytes(data)
    key = f"{SHOT_PREFIX}/{int(time.time())}-{os.getpid()}.png"
    stored = False
    try:
        api.client(call).raw("PUT", f"/blobs/{urllib.parse.quote(key)}", data)
        stored = True
    except CliError:
        stored = False
    if stored:
        out.line(markers.image(key, "image/png", call.flag("caption") or None))
    if call.on("send"):
        _send(call, data, key)
    out.send(
        {"bytes": len(data), "blob": key if stored else None, "path": target or None},
        [f"screenshot {len(data)} bytes" + (f" -> {target}" if target else "")],
    )
    return OK


def _send(call: Call, data: bytes, key: str) -> None:
    import base64

    body = {
        "name": Path(key).name,
        "data": base64.b64encode(data).decode(),
        "media": "photo",
        "caption": call.flag("caption") or None,
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/chat/files", body)
    sys.stdout.write(
        markers.emit(markers.BlockKind.SENT, message_ids=answer.get("message_ids") or []) + "\n"
    )


def tabs(call: Call, out: Out) -> int:
    state = _state(call)
    listing = browser.json_list(int(state["port"]))
    rows = [
        [str(index), item.get("title", "")[:48], item.get("url", "")[:60]]
        for index, item in enumerate(listing)
    ]
    if out.json_mode:
        out.send({"tabs": listing})
        return OK
    out.table(rows, ["#", "title", "url"])
    return OK


def tab(call: Call, out: Out) -> int:
    state = _state(call)
    action = call.arg("action")
    port = int(state["port"])
    if action == "new":
        browser.new_page(port, call.flag("url") or "about:blank")
        out.send({"opened": True}, ["opened a tab"])
        return OK
    listing = browser.json_list(port)
    index = int(call.arg("index") or "0")
    if index >= len(listing):
        raise CliError(f"there is no tab {index}", NOT_FOUND)
    target = listing[index]
    if action == "close":
        browser.close_page(port, str(target.get("id")))
        out.send({"closed": index}, [f"closed tab {index}"])
        return OK
    browser.activate_page(port, str(target.get("id")))
    out.send({"active": index}, [f"switched to tab {index}"])
    return OK


def upload(call: Call, out: Out) -> int:
    path = Path(call.arg("path")).resolve()
    if not path.is_file():
        raise CliError(f"no file at {path}", NOT_FOUND)
    return _simple(call, out, lambda cdp: actions.upload(cdp, call.arg("selector"), str(path)))


def cookies(call: Call, out: Out) -> int:
    cdp, _ = _open(call)
    try:
        if call.flag("import"):
            items = json.loads(Path(call.flag("import")).read_text(encoding="utf-8"))
            actions.set_cookies(cdp, items)
            out.send({"imported": len(items)}, [f"imported {len(items)} cookies"])
            return OK
        jar = actions.cookies(cdp)
    finally:
        cdp.close()
    if call.flag("export"):
        Path(call.flag("export")).write_text(json.dumps(jar, ensure_ascii=False), encoding="utf-8")
        out.send({"exported": len(jar)}, [f"exported {len(jar)} cookies"])
        return OK
    out.send({"cookies": jar}, [f"{len(jar)} cookies"])
    return OK


def profile(call: Call, out: Out) -> int:
    action = call.arg("action")
    name = call.arg("name")
    if action == "list":
        rows = [[item.name] for item in sorted(browser.PROFILES.glob("*")) if item.is_dir()]
        if out.json_mode:
            out.send({"profiles": [row[0] for row in rows]})
            return OK
        out.table(rows or [["(none)"]], ["profile"])
        return OK
    if not name:
        raise Usage("which profile?", "unsafie chrome profile export shopping")
    target = browser.PROFILES / name
    if action == "rm":
        shutil.rmtree(target, ignore_errors=True)
        out.send({"removed": name}, [f"removed {name}"])
        return OK
    if action == "export":
        key = f"profiles/{name}.tar.gz"
        blob = _pack(target)
        api.client(call).raw("PUT", f"/blobs/{urllib.parse.quote(key)}", blob)
        out.send({"blob": key, "bytes": len(blob)}, [f"stored {key} ({len(blob)} bytes)"])
        return OK
    if action == "import":
        key = call.flag("file") or f"profiles/{name}.tar.gz"
        data = api.client(call).download(f"/blobs/{urllib.parse.quote(key)}")
        _unpack(data, target)
        out.send({"profile": name}, [f"restored {name}"])
        return OK
    raise Usage("action must be list, rm, export or import")


def _pack(target: Path) -> bytes:
    import io

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(target, arcname=".")
    return buffer.getvalue()


def _unpack(data: bytes, target: Path) -> None:
    import io

    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(target, filter="data")


def desktop(call: Call, out: Out) -> int:
    state = _state(call)
    if state.get("headless"):
        raise CliError(
            "this chrome is headless, there is nothing to look at",
            FAILED,
            "restart it without --headless: unsafie chrome stop && unsafie chrome start",
        )
    answer = api.client(call).call(
        "POST", "/pool/desktop", {"display": state.get("display") or ":97"}
    )
    url_value = str(answer.get("url") or "")
    out.line(markers.link(url_value, "live desktop"))
    out.send(answer, [url_value])
    if call.on("open"):
        subprocess.run(["xdg-open", url_value], check=False, capture_output=True)
    return OK
