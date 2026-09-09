import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image as Pillow

from unsafie.cli import browser
from unsafie.cli.vision import attach


def test_vision_attach_valid_image():
    with tempfile.TemporaryDirectory() as tmpdir:
        img = Pillow.new("RGB", (50, 50), color="blue")
        img_path = Path(tmpdir) / "test.png"
        img.save(img_path, format="PNG")

        with patch("unsafie.cli.blobs.put") as mock_put, patch("sys.stderr.write") as mock_stderr:
            res = attach([str(img_path)])
            assert res["ok"] is True
            assert res["count"] == 1
            assert res["attached"][0]["mime"] == "image/png"
            assert res["attached"][0]["key"].startswith("vision/")
            assert mock_put.called
            assert mock_stderr.called


def test_vision_attach_nonexistent_file():
    res = attach(["/tmp/does_not_exist_12345.png"])
    assert res["ok"] is False
    assert "file not found" in res["error"]


def test_vision_attach_invalid_image_type():
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "not_an_image.txt"
        txt_path.write_text("just text", encoding="utf-8")

        res = attach([str(txt_path)])
        assert res["ok"] is False
        assert "not an image" in res["error"] or "format" in res["error"]


def test_vision_attach_multiple_images():
    with tempfile.TemporaryDirectory() as tmpdir:
        p1 = Path(tmpdir) / "img1.png"
        p2 = Path(tmpdir) / "img2.jpg"
        Pillow.new("RGB", (20, 20), color="red").save(p1, format="PNG")
        Pillow.new("RGB", (20, 20), color="green").save(p2, format="JPEG")

        with patch("unsafie.cli.blobs.put"), patch("sys.stderr.write"):
            res = attach([str(p1), str(p2)])
            assert res["ok"] is True
            assert res["count"] == 2
            assert res["attached"][0]["mime"] == "image/png"
            assert res["attached"][1]["mime"] == "image/jpeg"


def test_browser_shot_signature():
    import inspect

    sig = inspect.signature(browser.shot)
    params = list(sig.parameters.keys())
    assert "output" in params
    assert "full" in params
    assert "send" not in params
    assert "caption" not in params
