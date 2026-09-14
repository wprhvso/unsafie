from unittest.mock import patch

import pytest

from unsafie.agent import client
from unsafie.agent.client import Reply, _continuation_body, _merge_parts


def test_merge_parts():
    parts = [
        {"thought": True, "text": "Thinking "},
        {"thought": True, "text": "about things..."},
        {"thoughtSignature": "sig_xyz"},
        {"text": "Hello, "},
        {"text": "world!"},
    ]
    merged = _merge_parts(parts)
    assert len(merged) == 3
    assert merged[0] == {"thought": True, "text": "Thinking about things..."}
    assert merged[1] == {"thoughtSignature": "sig_xyz"}
    assert merged[2] == {"text": "Hello, world!"}


def test_continuation_body_appends_model_role():
    original_body = {"contents": [{"role": "user", "parts": [{"text": "Hi"}]}]}
    reply = Reply(
        text="partially generated",
        thoughts="thought",
        raw_parts=[
            {"thought": True, "text": "thought"},
            {"thoughtSignature": "sig"},
            {"text": "partially generated"},
        ],
    )
    new_body = _continuation_body(original_body, reply)
    contents = new_body["contents"]
    assert len(contents) == 2
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert len(contents[1]["parts"]) == 3
    assert contents[1]["parts"][0] == {"thought": True, "text": "thought"}
    assert contents[1]["parts"][1] == {"thoughtSignature": "sig"}
    assert contents[1]["parts"][2] == {"text": "partially generated"}


@pytest.mark.anyio
async def test_send_continuation_on_missing_finish_reason():
    cut_off_reply = Reply(
        model="gemini-3.1-pro-preview",
        text="First half ",
        raw_parts=[{"text": "First half "}],
        stop_reason=None,
    )
    finished_reply = Reply(
        model="gemini-3.1-pro-preview",
        text="First half second half!",
        raw_parts=[{"text": "First half "}, {"text": "second half!"}],
        stop_reason="STOP",
    )
    calls = 0

    async def fake_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return cut_off_reply, False
        return finished_reply, True

    with patch("unsafie.agent.client._once", side_effect=fake_once):
        res = await client.send("token", "gemini-3.1-pro-preview", {"contents": []})
        assert calls == 2
        assert res.stop_reason == "STOP"
        assert res.text == "First half second half!"


@pytest.mark.anyio
async def test_send_non_retryable_finish_reason():
    safety_reply = Reply(
        model="gemini-3.1-pro-preview",
        text="I cannot assist with that",
        stop_reason="SAFETY",
    )
    with patch("unsafie.agent.client._once", return_value=(safety_reply, True)):
        res = await client.send("token", "gemini-3.1-pro-preview", {"contents": []})
        assert res.stop_reason == "SAFETY"
