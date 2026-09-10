import io
import tempfile
from pathlib import Path

from PIL import Image as Pillow

from unsafie.bloat2md import Kind, convert
from unsafie.cli.bloat2md import run


def test_convert_plain_text() -> None:
    raw = b"Hello world\nSecond line"
    kind, payload = convert(raw, "doc.txt")
    assert kind == Kind.TEXT
    assert "Hello world" in payload.markdown


def test_convert_csv() -> None:
    raw = b"col1,col2\nval1,val2\n"
    kind, payload = convert(raw, "table.csv")
    assert kind == Kind.CSV
    assert "| col1 | col2 |" in payload.markdown


def test_convert_json() -> None:
    raw = b'{"name": "test", "items": [1, 2]}'
    kind, payload = convert(raw, "data.json")
    assert kind == Kind.JSON
    assert '"name": "test"' in payload.markdown


def test_convert_html() -> None:
    raw = b"<html><body><h1>Title</h1><p>Paragraph</p></body></html>"
    kind, payload = convert(raw, "page.html")
    assert kind == Kind.HTML
    assert "Title" in payload.markdown
    assert "Paragraph" in payload.markdown


def test_convert_image() -> None:
    img = Pillow.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    kind, payload = convert(buf.getvalue(), "pic.png")
    assert kind == Kind.IMAGE
    assert len(payload.images) == 1


def test_cli_run_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        infile = Path(tmpdir) / "sample.csv"
        infile.write_text("a,b\n1,2\n", encoding="utf-8")
        outfile = Path(tmpdir) / "sample.md"

        res = run(str(infile), output=str(outfile), no_sandbox=True)
        assert res["ok"] is True
        assert res["kind"] == "csv"
        assert outfile.is_file()
        assert "| a | b |" in outfile.read_text(encoding="utf-8")
