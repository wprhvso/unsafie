import io
import tarfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import CommandObject
from aiogram.types import Chat, Message, User

from unsafie.database import SessionLocal
from unsafie.database.models.response import Response
from unsafie.database.models.turn import Turn, TurnStatus
from unsafie.database.models.turn_message import TurnMessages
from unsafie.database.repositories.turn import TurnRepository
from unsafie.telegram.handlers.commands.load import (
    build_load_router,
    fetch_repo_files,
    format_repo_markdown,
    make_fence,
    parse_repo_arg,
)


def test_parse_repo_arg():
    assert parse_repo_arg("octocat/Hello-World") == ("octocat", "Hello-World", None)
    assert parse_repo_arg("octocat/Hello-World@dev") == ("octocat", "Hello-World", "dev")
    assert parse_repo_arg("https://github.com/octocat/Hello-World.git") == (
        "octocat",
        "Hello-World",
        None,
    )
    assert parse_repo_arg("http://github.com/octocat/Hello-World") == (
        "octocat",
        "Hello-World",
        None,
    )
    assert parse_repo_arg("github.com/octocat/Hello-World/tree/feature/test") == (
        "octocat",
        "Hello-World",
        "feature/test",
    )
    with pytest.raises(ValueError, match="Invalid repository"):
        parse_repo_arg("invalid")
    with pytest.raises(ValueError, match="Invalid repository"):
        parse_repo_arg("too/many/slashes/here")


def test_make_fence():
    b3 = chr(96) * 3
    b4 = chr(96) * 4
    b5 = chr(96) * 5
    assert make_fence("hello world") == b3
    assert make_fence(f"hello {b3} world") == b4
    assert make_fence(f"hello {b4} world") == b5


def test_format_repo_markdown():
    files = {
        "src/main.py": "print('hello')",
        "assets/logo.png": "[Binary file, 10 KB]",
    }
    md = format_repo_markdown("myorg", "myrepo", "main", files)
    assert "# Repository: myorg/myrepo@main" in md
    assert "## src/main.py" in md
    assert "print('hello')" in md
    assert "## assets/logo.png" in md
    assert "[Binary file, 10 KB]" in md


@pytest.mark.asyncio
async def test_fetch_repo_files_from_tarball(tmp_path):
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        t_txt = tarfile.TarInfo(name="repo-root/src/app.py")
        data_txt = b"def main(): pass\n"
        t_txt.size = len(data_txt)
        tar.addfile(t_txt, io.BytesIO(data_txt))

        t_bin = tarfile.TarInfo(name="repo-root/data.bin")
        data_bin = b"\x00\x01\x02\x03\x04"
        t_bin.size = len(data_bin)
        tar.addfile(t_bin, io.BytesIO(data_bin))

        t_skip = tarfile.TarInfo(name="repo-root/node_modules/pkg/index.js")
        data_skip = b"console.log('skip');"
        t_skip.size = len(data_skip)
        tar.addfile(t_skip, io.BytesIO(data_skip))

        t_ds = tarfile.TarInfo(name="repo-root/.DS_Store")
        data_ds = b"junk"
        t_ds.size = len(data_ds)
        tar.addfile(t_ds, io.BytesIO(data_ds))

    tar_bytes = tar_buf.getvalue()

    async def fake_stream(url, dest, limit):
        dest.write_bytes(tar_bytes)
        return len(tar_bytes)

    with patch("unsafie.telegram.handlers.commands.load.RepoClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.base = "/repos/octocat/Hello-World"
        mock_client.stream = AsyncMock(side_effect=fake_stream)
        mock_client_cls.return_value = mock_client

        files = await fetch_repo_files(12345, "octocat", "Hello-World", None)

    assert "src/app.py" in files
    assert files["src/app.py"] == "def main(): pass\n"
    assert "data.bin" in files
    assert "[Binary file" in files["data.bin"]
    assert "node_modules/pkg/index.js" not in files
    assert ".DS_Store" not in files


@pytest.mark.asyncio
async def test_load_command_handler(monkeypatch):
    router = build_load_router()
    handler = router.message.handlers[0].callback

    user = User(id=99999, is_bot=False, first_name="Test", language_code="ru")
    chat = Chat(id=88888, type="private")
    bot = AsyncMock()

    sent_messages = []

    async def fake_send(
        b,
        bot_id,
        chat_id,
        markdown,
        kind,
        turn=None,
        reply_to=None,
        reply_markup=None,
        silent=False,
        preview=True,
    ):
        sent_messages.append((markdown, turn))
        async with SessionLocal() as session:
            resp = Response(
                bot_id=bot_id,
                chat_id=chat_id,
                turn_id=turn.id if turn else None,
                kind=kind,
                content=markdown,
                message_ids=[77777],
                reply_to=reply_to,
            )
            session.add(resp)
            await session.commit()
            await session.refresh(resp)
            return resp

    monkeypatch.setattr("unsafie.telegram.sender.send", fake_send)

    async def fake_answer(message, bot_id, text, reply_markup=None):
        sent_messages.append((text, None))

    monkeypatch.setattr("unsafie.telegram.sender.answer", fake_answer)

    async def fake_fetch(user_id, owner, name, branch):
        return {"README.md": "# Hello World\nTesting load command."}

    monkeypatch.setattr(
        "unsafie.telegram.handlers.commands.load.fetch_repo_files",
        fake_fetch,
    )

    msg = Message(
        message_id=55555,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text="/load octocat/Hello-World",
    ).as_(bot)
    cmd = CommandObject(prefix="/", command="load", args="octocat/Hello-World")

    await handler(msg, cmd, bot_id=1, update_db_id=None)

    assert len(sent_messages) == 1
    reply_text, turn = sent_messages[0]
    assert turn is not None
    assert "octocat/Hello-World" in reply_text
    assert "символов" in reply_text

    async with SessionLocal() as session:
        t_repo = TurnRepository(session)
        turn_row = await t_repo.get(turn.id)
        assert turn_row is not None
        assert turn_row.status == TurnStatus.DONE

        owner = await t_repo.owner(1, 88888, 77777)
        assert owner is not None
        assert owner.id == turn.id

        from unsafie.agent import segments

        history = await segments.load(
            Turn(
                id=turn.id,
                bot_id=1,
                chat_id=88888,
                user_id=99999,
                parent_id=turn.id,
                root_id=turn.id,
            )
        )
        assert len(history.messages) == 2
        assert "README.md" in history.messages[0]["content"]

        from sqlalchemy import delete

        await session.execute(delete(TurnMessages).where(TurnMessages.turn_id == turn.id))
        await session.execute(delete(Response).where(Response.turn_id == turn.id))
        await session.execute(delete(Turn).where(Turn.id == turn.id))
        await session.commit()
