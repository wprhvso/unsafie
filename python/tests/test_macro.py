import tempfile
from pathlib import Path

from unsafie.agent.parser import extract_code
from unsafie.cli import read
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


def test_cli_read_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = Path(tmpdir) / "file1.txt"
        f2 = Path(tmpdir) / "file2.txt"
        f1.write_text("line1\nline2\nline3\n", encoding="utf-8")
        f2.write_text("alpha\nbeta\n", encoding="utf-8")

        res = read.read([str(f1), str(f2)])
        assert res["ok"] is True
        assert res["count"] == 2
        assert res["total_lines_read"] == 5
        assert "=== " in res["rendered"]
        assert "line1" in res["rendered"]
        assert "beta" in res["rendered"]


def test_cli_read_line_range():
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "sample.py"
        f.write_text("\n".join(f"item_{i}" for i in range(1, 21)), encoding="utf-8")

        res = read.read([str(f)], lines="5-10")
        assert res["ok"] is True
        assert res["total_lines_read"] == 6
        assert "item_5" in res["rendered"]
        assert "item_10" in res["rendered"]
        assert "item_1\n" not in res["rendered"]
        assert "item_4\n" not in res["rendered"]
        assert "item_11" not in res["rendered"]
