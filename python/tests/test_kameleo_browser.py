from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unsafie.api.routes.public import machine
from unsafie.chrome import browser, vnc
from unsafie.chrome.cdp import CdpError
from unsafie.cli import browser as cli_browser


def test_browser_launch_creates_profile():
    mock_client = MagicMock()
    mock_fp = MagicMock(id="fp-123")
    mock_client.fingerprint.search_fingerprints.return_value = [mock_fp]
    mock_profile = MagicMock(id="prof-456")
    mock_client.profile.create_profile.return_value = mock_profile

    with patch.object(browser, "_client", return_value=(mock_client, "127.0.0.1", 5050)):
        state = browser.launch(profile="test-prof", size="1280x720", headless=True)

    assert state["port"] == 5050
    assert state["profile"] == "test-prof"
    assert state["profile_id"] == "prof-456"
    assert state["endpoint"] == "ws://127.0.0.1:5050/playwright/prof-456"
    assert state["vnc_port"] is None
    mock_client.profile.create_profile.assert_called_once()


def test_browser_launch_reuses_existing_profile():
    mock_client = MagicMock()
    mock_fp = MagicMock(id="fp-123")
    mock_client.fingerprint.search_fingerprints.return_value = [mock_fp]
    existing = MagicMock(id="prof-existing")
    existing.name = "my-profile"
    mock_client.profile.list_profiles.return_value = [existing]

    with patch.object(browser, "_client", return_value=(mock_client, "127.0.0.1", 5050)), \
         patch.object(vnc, "ensure", return_value=""), \
         patch.object(vnc, "listening", return_value=True), \
         patch("unsafie.pool.tunnels.publish_sync", return_value="test-slug"):
        state = browser.launch(profile="my-profile", size="1920x1080", headless=False)

    assert state["profile_id"] == "prof-existing"
    assert state["vnc_port"] == 5900
    assert state["vnc_slug"] == "test-slug"
    assert "/m/test-slug" in state["vnc_url"]
    mock_client.profile.create_profile.assert_not_called()


def test_browser_stop_calls_kameleo():
    mock_client = MagicMock()
    with patch.object(browser, "_client", return_value=(mock_client, "127.0.0.1", 5050)):
        browser.stop({"profile_id": "prof-999"})

    mock_client.profile.stop_profile.assert_called_once_with("prof-999")


def test_browser_session_direct():
    mock_cdp = MagicMock()
    with patch.object(browser, "connect", return_value=mock_cdp):
        cdp, ep = browser.session({"endpoint": "ws://127.0.0.1:5050/playwright/prof-1"})

    assert cdp == mock_cdp
    assert ep == "ws://127.0.0.1:5050/playwright/prof-1"
    mock_cdp.call.assert_any_call("Page.enable")


def test_browser_session_target_attach_fallback():
    mock_cdp = MagicMock()

    def mock_call(method, *args, **kwargs):
        if method == "Page.enable" and mock_cdp.session_id is None:
            msg = "domain not available"
            raise CdpError(msg)
        if method == "Target.getTargets":
            return {"targetInfos": [{"type": "page", "targetId": "target-page-1"}]}
        if method == "Target.attachToTarget":
            return {"sessionId": "sess-page-1"}
        return {}

    mock_cdp.call.side_effect = mock_call
    mock_cdp.session_id = None

    with patch.object(browser, "connect", return_value=mock_cdp):
        cdp, _ = browser.session({"endpoint": "ws://127.0.0.1:5050/playwright/prof-2"})

    assert cdp.session_id == "sess-page-1"


def test_cli_browser_start_and_stop(tmp_path: Path):
    fake_state = {
        "port": 5050,
        "endpoint": "ws://127.0.0.1:5050/playwright/prof-test",
        "profile_id": "prof-test",
        "profile": "p1",
        "vnc_port": 5900,
        "vnc_slug": "prof-slug",
        "vnc_url": "https://unsafie.com/m/prof-slug",
    }
    state_file = tmp_path / "kameleo.json"

    with patch.object(browser, "state_file", return_value=state_file), \
         patch.object(browser, "launch", return_value=fake_state), \
         patch.object(browser, "_alive", return_value=True):
        res_start = cli_browser.start("p1")
        assert res_start["running"] is True
        assert res_start["profile_id"] == "prof-test"
        assert res_start["vnc_port"] == 5900
        assert res_start["vnc_url"] == "https://unsafie.com/m/prof-slug"
        assert state_file.is_file()

        with patch.object(browser, "stop") as mock_stop:
            res_stop = cli_browser.stop()
            assert res_stop["stopped"] is True
            mock_stop.assert_called_once()
            assert not state_file.exists()


@pytest.mark.anyio
async def test_machine_stream_local_connect():
    mock_ws = AsyncMock()
    mock_ws.headers = {"sec-websocket-protocol": "binary"}
    mock_ws.receive.side_effect = [{"type": "websocket.disconnect"}]

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b""
    mock_writer = AsyncMock()

    with patch("unsafie.pool.tunnels.resolve", return_value={"kind": "vnc", "machine": "local", "port": 5900}), \
         patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        await machine.stream(mock_ws, "test-slug")

    mock_ws.accept.assert_called_once_with(subprotocol="binary")
