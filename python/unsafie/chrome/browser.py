import contextlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kameleo.local_api_client.kameleo_local_api_client import KameleoLocalApiClient
from kameleo.local_api_client.models.create_profile_request import CreateProfileRequest

from unsafie.chrome import vnc
from unsafie.chrome.cdp import Cdp, CdpError
from unsafie.settings import settings

STATE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/run") / "unsafie"


class BrowserError(RuntimeError):
    pass


def state_dir() -> Path:
    target = Path.home() / ".local" / "state" / "unsafie"
    target.mkdir(parents=True, exist_ok=True)
    return target


def state_file() -> Path:
    token = os.environ.get("UNSAFIE_CHAT") or os.environ.get("UNSAFIE_TURN")
    filename = f"kameleo_{token}.json" if token else "kameleo.json"
    return state_dir() / filename


def save(state: dict) -> None:
    state_file().write_text(json.dumps(state), encoding="utf-8")


def forget() -> None:
    state_file().unlink(missing_ok=True)


def _client() -> tuple[KameleoLocalApiClient, str, int]:
    port = int(os.environ.get("KAMELEO_PORT") or settings.kameleo_port)
    endpoint = (
        os.environ.get("KAMELEO_URL")
        or os.environ.get("KAMELEO_ENDPOINT")
        or f"http://127.0.0.1:{port}"
    )
    client = KameleoLocalApiClient(endpoint=endpoint)
    try:
        client.verify_engine_ready()
    except Exception as broken:
        msg = f"kameleo engine is not ready at {endpoint}: {broken}"
        raise BrowserError(msg) from None
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    resolved_port = parsed.port or port
    return client, host, resolved_port


def launch(profile: str | None = None, size: str = "1920x1080", headless: bool = False) -> dict:
    client, host, port = _client()
    fingerprints = client.fingerprint.search_fingerprints(
        device_type=settings.kameleo_device_type,
        browser_product=settings.kameleo_browser_product,
    )
    if not fingerprints:
        msg = "no fingerprints available from kameleo"
        raise BrowserError(msg)

    profile_name = profile or f"unsafie-{int(time.time() * 1000)}"
    profile_id: str | None = None

    if profile:
        with contextlib.suppress(Exception):
            existing = client.profile.list_profiles()
            for item in existing:
                if item.name == profile or item.id == profile:
                    profile_id = item.id
                    break

    if not profile_id:
        req = CreateProfileRequest(
            fingerprintId=fingerprints[0].id,
            name=profile_name,
        )
        created = client.profile.create_profile(req)
        profile_id = created.id

    vnc_port = None
    vnc_slug = None
    vnc_url = None
    if not headless:
        vnc.ensure(size, display=vnc.DISPLAY)
        if vnc.listening(vnc.RFB_PORT, 2.0):
            vnc_port = vnc.RFB_PORT
            with contextlib.suppress(Exception):
                import uuid

                from unsafie import artifacts
                from unsafie.pool import tunnels
                from unsafie.slugs import generate_slug

                vnc_slug = generate_slug()
                tunnels.publish_sync(0, "local", "vnc", vnc_port, slug=vnc_slug)
                turn_env = os.environ.get("UNSAFIE_TURN")
                chat_env = os.environ.get("UNSAFIE_CHAT")
                turn_uuid = uuid.UUID(turn_env) if turn_env else None
                chat_id = int(chat_env) if chat_env and chat_env.lstrip("-").isdigit() else None
                artifacts.publish_desktop_sync(
                    slug=vnc_slug,
                    title=f"Desktop · {profile_name}",
                    turn_id=turn_uuid,
                    chat_id=chat_id,
                )
                vnc_url = artifacts.url(vnc_slug)

    endpoint = f"ws://{host}:{port}/playwright/{profile_id}"
    return {
        "port": port,
        "endpoint": endpoint,
        "profile": profile_name,
        "profile_id": profile_id,
        "headless": headless,
        "size": size,
        "vnc_port": vnc_port,
        "vnc_slug": vnc_slug,
        "vnc_url": vnc_url,
        "started_at": time.time(),
    }


def connect(endpoint: str, timeout: float = 30.0) -> Cdp:
    try:
        return Cdp(endpoint, timeout)
    except Exception as broken:
        msg = f"cannot reach the browser: {broken}"
        raise BrowserError(msg) from None


def session(state: dict) -> tuple[Cdp, str]:
    endpoint = state.get("endpoint")
    if not endpoint:
        msg = "the browser has no endpoint configured"
        raise BrowserError(msg)
    cdp = connect(endpoint)
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("DOM.enable")
    except CdpError:
        targets = cdp.call("Target.getTargets")
        page_targets = [t for t in targets.get("targetInfos", []) if t.get("type") == "page"]
        if not page_targets:
            created = cdp.call("Target.createTarget", {"url": "about:blank"})
            target_id = created.get("targetId")
        else:
            target_id = page_targets[0]["targetId"]
        attached = cdp.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        cdp.session_id = attached.get("sessionId")
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("DOM.enable")
    return cdp, endpoint


def stop(state: dict) -> None:
    profile_id = state.get("profile_id")
    if profile_id:
        with contextlib.suppress(Exception):
            client, _, _ = _client()
            client.profile.stop_profile(profile_id)
    pkill = shutil.which("pkill")
    if pkill and not state.get("headless"):
        subprocess.run([pkill, "-f", f"kasmxproxy.*{vnc.DISPLAY}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([pkill, "-f", f"x11vnc.*{vnc.RFB_PORT}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([pkill, "-f", f"Xkasmvnc.*{vnc.RFB_PORT}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _alive(profile_id: str) -> bool:
    try:
        client, _, _ = _client()
        status = client.profile.get_profile_status(profile_id)
        return any(s in str(status.lifetime_state).lower() for s in ("running", "starting", "created"))
    except Exception:
        return False


def load() -> dict | None:
    target = state_file()
    if not target.is_file():
        return None
    try:
        state: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None
    profile_id = state.get("profile_id")
    if profile_id and not _alive(profile_id):
        target.unlink(missing_ok=True)
        return None
    return state
