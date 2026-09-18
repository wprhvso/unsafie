from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from unsafie.agent.blocks import Runner
from unsafie.agent.session import Ctx


@pytest.mark.anyio
async def test_bwrap_resolv_conf_symlink_not_mounted_on_dest(tmp_path: Path) -> None:
    bot = MagicMock()
    ctx = Ctx(
        bot=bot,
        bot_id=1,
        chat_id=12345,
        user_id=67890,
        turn_id=uuid4(),
        locale="en",
        machine_name="sandbox",
    )
    recorder = MagicMock()
    runner = Runner(ctx, recorder)

    captured_argv: list[str] = []

    async def fake_subprocess_exec(*argv, **kwargs):
        nonlocal captured_argv
        captured_argv = list(argv)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
        return proc

    fake_symlink = tmp_path / "resolv.conf"
    target_file = tmp_path / "stub-resolv.conf"
    target_file.write_text("nameserver 1.1.1.1\n", encoding="utf-8")
    fake_symlink.symlink_to(target_file)

    def fake_path(*args, **kwargs):
        if args and str(args[0]) == "/etc/resolv.conf":
            return fake_symlink
        return Path(*args, **kwargs)

    with (
        patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
        patch("unsafie.agent.blocks.Path", side_effect=fake_path),
        patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec),
        patch.object(runner, "_ensure_token", new_callable=AsyncMock, return_value="token123"),
    ):
        block = await runner.run("echo hello", index=1)

    assert block.exit_code == 0
    assert block.output == "hello\n"

    for i in range(len(captured_argv) - 2):
        if captured_argv[i] in ("--ro-bind", "--ro-bind-try", "--bind", "--dev-bind"):
            dest = captured_argv[i + 2]
            assert dest != "/etc/resolv.conf"

    assert str(target_file) in captured_argv
