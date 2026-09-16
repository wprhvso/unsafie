from unittest.mock import AsyncMock, patch

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
async def test_send_aistudio_success():
    mock_cli = AsyncMock()
    mock_cli.generate.return_value = "```bash\necho ok\n```"
    with patch("unsafie.aistudio.client.get_default_client", return_value=mock_cli):
        res = await client.send("tok", "gemini-flash", {"contents": []})
        assert res.text == "```bash\necho ok\n```"
        assert res.stop_reason == "STOP"
