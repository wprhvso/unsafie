from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from unsafie.chrome import actions
from unsafie.chrome.cdp import CdpError
from unsafie.cli import browser as cli_browser


def test_navigation_back_and_forward():
    mock_cdp = MagicMock()
    mock_cdp.call.side_effect = lambda method, params=None: {
        "Page.getNavigationHistory": {
            "currentIndex": 1,
            "entries": [{"id": 10}, {"id": 20}, {"id": 30}],
        },
        "Runtime.evaluate": {"result": {"value": "https://example.com"}},
    }.get(method, {})

    res_back = actions.back(mock_cdp, timeout=5.0)
    assert res_back["navigated"] == "back"
    assert res_back["entry_id"] == 10
    mock_cdp.call.assert_any_call("Page.navigateToHistoryEntry", {"entryId": 10})

    res_fwd = actions.forward(mock_cdp, timeout=5.0)
    assert res_fwd["navigated"] == "forward"
    assert res_fwd["entry_id"] == 30
    mock_cdp.call.assert_any_call("Page.navigateToHistoryEntry", {"entryId": 30})


def test_navigation_history_errors():
    mock_cdp = MagicMock()
    mock_cdp.call.return_value = {
        "currentIndex": 0,
        "entries": [{"id": 10}],
    }
    with pytest.raises(CdpError):
        actions.back(mock_cdp)
    with pytest.raises(CdpError):
        actions.forward(mock_cdp)


def test_reload_page():
    mock_cdp = MagicMock()
    mock_cdp.call.side_effect = lambda method, params=None: {
        "Runtime.evaluate": {"result": {"value": "https://example.com/reloaded"}},
    }.get(method, {})
    res = actions.reload_page(mock_cdp, ignore_cache=True, timeout=5.0)
    assert res["reloaded"] is True
    assert res["ignore_cache"] is True
    mock_cdp.call.assert_any_call("Page.reload", {"ignoreCache": True})


def test_title_and_hover():
    mock_cdp = MagicMock()
    mock_cdp.call.side_effect = lambda method, params=None: {
        "Runtime.evaluate": {"result": {"value": "Test Page"}},
    }.get(method, {})
    assert actions.title_of(mock_cdp) == "Test Page"

    with patch.object(actions, "centre", return_value=(50.0, 100.0)):
        coords = actions.hover(mock_cdp, "#target")
        assert coords == (50.0, 100.0)
        mock_cdp.call.assert_any_call(
            "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 50.0, "y": 100.0}
        )


def test_drag_action():
    mock_cdp = MagicMock()
    with patch.object(actions, "centre", side_effect=[(10.0, 20.0), (100.0, 200.0)]):
        actions.drag(mock_cdp, "#a", "#b", steps=2)
        mock_cdp.call.assert_any_call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": 10.0,
                "y": 20.0,
                "button": "left",
                "clickCount": 1,
                "buttons": 1,
            },
        )
        mock_cdp.call.assert_any_call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": 100.0,
                "y": 200.0,
                "button": "left",
                "clickCount": 1,
                "buttons": 0,
            },
        )


def test_query_elements():
    mock_cdp = MagicMock()
    mock_cdp.call.return_value = {
        "result": {
            "value": [
                {
                    "index": 0,
                    "tag": "button",
                    "text": "OK",
                    "visible": True,
                    "rect": {"x": 10, "y": 20, "width": 50, "height": 30},
                    "attributes": {"id": "btn"},
                },
            ],
        },
    }
    items = actions.query_elements(mock_cdp, "button", limit=5)
    assert len(items) == 1
    assert items[0]["tag"] == "button"


def test_scroll_actions():
    mock_cdp = MagicMock()
    mock_cdp.call.return_value = {
        "result": {"value": {"x": 0, "y": 200, "maxX": 1000, "maxY": 2000}}
    }
    res_by = actions.scroll(mock_cdp, by="0,100")
    assert res_by["scrolled"] is True
    assert res_by["scroll_y"] == 200
    mock_cdp.call.assert_any_call(
        "Input.dispatchMouseEvent",
        {"type": "mouseWheel", "x": 100, "y": 100, "deltaX": 0.0, "deltaY": 100.0},
    )


def test_network_and_blocking():
    mock_cdp = MagicMock()
    actions.set_blocked_urls(mock_cdp, ["*.png"])
    mock_cdp.call.assert_any_call("Network.enable")
    mock_cdp.call.assert_any_call("Network.setBlockedURLs", {"urls": ["*.png"]})

    mock_cdp.call.return_value = {
        "result": {
            "value": [
                {
                    "name": "https://api.com/v1",
                    "type": "fetch",
                    "duration": 45,
                    "size": 200,
                    "start": 10,
                },
                {
                    "name": "https://img.com/a.png",
                    "type": "img",
                    "duration": 15,
                    "size": 500,
                    "start": 12,
                },
            ],
        },
    }
    net = actions.network_log(mock_cdp, pattern="api")
    assert net["count"] == 1
    assert net["requests"][0]["name"] == "https://api.com/v1"


def test_tabs_management():
    mock_cdp = MagicMock()
    mock_cdp.call.side_effect = lambda method, params=None: {
        "Target.getTargets": {
            "targetInfos": [
                {"targetId": "tab-1", "type": "page", "title": "Page 1", "url": "https://p1.com"},
                {"targetId": "tab-2", "type": "page", "title": "Page 2", "url": "https://p2.com"},
                {"targetId": "bg-1", "type": "service_worker"},
            ],
        },
        "Target.createTarget": {"targetId": "tab-3"},
    }.get(method, {})

    tabs = actions.list_tabs(mock_cdp)
    assert len(tabs) == 2
    assert tabs[0]["id"] == "tab-1"

    new_id = actions.new_tab(mock_cdp, "https://p3.com")
    assert new_id == "tab-3"

    actions.switch_tab(mock_cdp, "tab-2")
    mock_cdp.call.assert_any_call("Target.activateTarget", {"targetId": "tab-2"})

    actions.close_tab(mock_cdp, "tab-1")
    mock_cdp.call.assert_any_call("Target.closeTarget", {"targetId": "tab-1"})


def test_frames():
    mock_cdp = MagicMock()
    mock_cdp.call.side_effect = lambda method, params=None: {
        "Page.getFrameTree": {
            "frameTree": {
                "frame": {"id": "root", "url": "https://site.com", "name": "main"},
                "childFrames": [
                    {"frame": {"id": "child-1", "url": "https://pay.com", "name": "frame_pay"}},
                ],
            },
        },
        "DOM.getDocument": {"root": {"nodeId": 1}},
        "DOM.querySelector": {"nodeId": 2},
        "DOM.describeNode": {"node": {"frameId": "child-1"}},
    }.get(method, {})

    tree = actions.frame_tree(mock_cdp)
    assert len(tree) == 2
    assert tree[0]["id"] == "root"
    assert tree[1]["id"] == "child-1"

    fid = actions.find_frame_id(mock_cdp, "iframe#pay")
    assert fid == "child-1"


def test_intercept_request():
    mock_cdp = MagicMock()
    mock_cdp.events.return_value = [
        {
            "method": "Fetch.requestPaused",
            "requestId": "req-123",
            "request": {
                "url": "https://api.com/checkout",
                "method": "POST",
                "headers": {"content-type": "application/json"},
                "postData": '{"price": 100}',
            },
        },
    ]
    res = actions.intercept_request(mock_cdp, "*checkout*", block=True, timeout=1.0)
    assert res["intercepted"] is True
    assert res["blocked"] is True
    assert res["method"] == "POST"
    assert res["body_json"] == {"price": 100}
    mock_cdp.call.assert_any_call(
        "Fetch.failRequest", {"requestId": "req-123", "errorReason": "BlockedByClient"}
    )


def test_cli_upload(tmp_path: Path):
    test_file = tmp_path / "doc.txt"
    test_file.write_text("content", encoding="utf-8")
    mock_cdp = MagicMock()
    mock_cdp.call.side_effect = lambda method, params=None: {
        "DOM.getDocument": {"root": {"nodeId": 1}},
        "DOM.querySelector": {"nodeId": 2},
        "Runtime.evaluate": {"result": {}},
    }.get(method, {})

    with patch.object(cli_browser, "_session", return_value=mock_cdp):
        res = cli_browser.upload("input[type=file]", str(test_file))
        assert res["uploaded"] == "input[type=file]"
        assert res["bytes"] == 7

    with pytest.raises(FileNotFoundError):
        cli_browser.upload("input[type=file]", str(tmp_path / "nonexistent.txt"))
