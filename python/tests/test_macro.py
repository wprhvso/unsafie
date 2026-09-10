import asyncio
import tempfile
import uuid
from pathlib import Path

from unsafie.agent.parser import extract_code
from unsafie.agent.spool import BashSpool
from unsafie.settings import settings


def test_parser_extract_code_with_surrounding_text():
    text = "Some introductory thinking text\n```bash\necho hello\n```\nSome concluding words"
    assert extract_code(text) == "echo hello"


def test_parser_extract_code_standard():
    text = "```bash\nunsafie chat send 'ok'\nunsafie stop\n```"
    assert extract_code(text) == "unsafie chat send 'ok'\nunsafie stop"


def test_parser_extract_code_no_markdown_fence():
    text = "echo 'raw bash'"
    assert extract_code(text) == "echo 'raw bash'"


def test_settings_limits():
    assert settings.pool_max_output == 4_000_000
    assert getattr(settings, "pool_max_output_lines", None) == 4_000_000


def test_spool_step_isolation():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        tid = uuid.uuid4()
        spool1 = BashSpool(tid, 1, base_dir=base)
        spool1.prepare("echo 'output_step_1'")
        asyncio.run(spool1.launch())
        asyncio.run(spool1.wait())
        out1 = spool1.read_output().strip()
        assert out1 == "output_step_1"

        spool2 = BashSpool(tid, 2, base_dir=base)
        spool2.prepare("echo 'output_step_2'")
        asyncio.run(spool2.launch())
        asyncio.run(spool2.wait())
        out2 = spool2.read_output().strip()
        assert out2 == "output_step_2"
        assert "output_step_1" not in out2

        spool1_rerun = BashSpool(tid, 1, base_dir=base)
        spool1_rerun.prepare("echo 'output_step_1_rerun'")
        asyncio.run(spool1_rerun.launch())
        asyncio.run(spool1_rerun.wait())
        out1_rerun = spool1_rerun.read_output().strip()
        assert out1_rerun == "output_step_1_rerun"
        assert "output_step_1\n" not in out1_rerun
