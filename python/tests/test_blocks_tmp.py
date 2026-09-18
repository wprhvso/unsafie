from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from unsafie.agent.blocks import Runner
from unsafie.agent.session import Ctx
from unsafie.settings import settings


@pytest.mark.asyncio
async def test_runner_tmp_directory_persists(tmp_path: Path):
    settings.chats_dir = tmp_path / "chats"
    chat_id = 12345
    ctx = Ctx(
        bot=MagicMock(),
        bot_id=1,
        chat_id=chat_id,
        user_id=67890,
        turn_id=uuid4(),
    )
    recorder = MagicMock()
    runner = Runner(ctx, recorder)

    proc_mock = AsyncMock()
    proc_mock.returncode = 0
    proc_mock.communicate = AsyncMock(return_value=(b"ok", b""))

    captured_argv: list[str] = []

    async def fake_exec(*args: str, **kwargs: object) -> AsyncMock:
        captured_argv.extend(args)
        return proc_mock

    with (
        patch("shutil.which", side_effect=lambda x: f"/bin/{x}"),
        patch("unsafie.tokens.issue", AsyncMock(return_value=(1, "test-token"))),
        patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
    ):
        await runner.run("echo 1")

    expected_tmp = tmp_path / "chats" / str(chat_id) / "tmp"
    expected_work = tmp_path / "chats" / str(chat_id) / "work"
    expected_home = tmp_path / "chats" / str(chat_id) / "home"

    assert expected_tmp.is_dir()
    assert expected_work.is_dir()
    assert expected_home.is_dir()

    assert "--tmpfs" not in captured_argv
    bind_idx = captured_argv.index(str(expected_tmp))
    assert captured_argv[bind_idx - 1] == "--bind"
    assert captured_argv[bind_idx + 1] == "/tmp"
