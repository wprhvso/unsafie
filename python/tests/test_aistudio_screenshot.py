from __future__ import annotations

from pathlib import Path

from unsafie.aistudio.browser import _format_screenshot_path
from unsafie.settings import settings


def test_format_screenshot_path_custom_template() -> None:
    settings.aistudio_screenshot_pattern = "/tmp/test_shots/{profile_id}_{reason}.png"
    p = _format_screenshot_path("prof123", reason="timeout")
    assert str(p) == "/tmp/test_shots/prof123_timeout.png"
    assert isinstance(p, Path)
