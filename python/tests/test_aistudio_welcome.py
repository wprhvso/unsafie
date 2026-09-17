from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from unsafie.aistudio.browser import AistudioBrowser, UnusableProfileError
from unsafie.aistudio.pool import AistudioPoolManager


@pytest.mark.anyio
async def test_check_welcome_page_raises_on_welcome_url() -> None:
    session = AsyncMock()
    profile = {"id": "p1", "name": "WelcomeUser"}
    browser = AistudioBrowser(session=session, profile=profile)

    with patch.object(browser, "get_current_url", AsyncMock(return_value="https://aistudio.google.com/welcome")):
        with patch.object(browser, "capture_error_screenshot", AsyncMock(return_value="/tmp/test.png")):
            with pytest.raises(UnusableProfileError):
                await browser.check_welcome_page()


@pytest.mark.anyio
async def test_pool_discards_welcome_profile_on_start() -> None:
    pool = AistudioPoolManager(endpoint="http://mock:5050", max_active_profiles=2)
    profiles = [
        {"id": "welcome-profile", "name": "Welcome", "tags": ["aistudio-api"]},
        {"id": "normal-profile", "name": "Working", "tags": ["aistudio-api"]},
    ]

    async def mock_enter(self_browser):
        return self_browser

    async def mock_check_welcome(self_browser):
        if self_browser.profile["id"] == "welcome-profile":
            raise UnusableProfileError("redirected to welcome")

    with (
        patch.object(pool, "load_profiles", AsyncMock(return_value=profiles)),
        patch("unsafie.aistudio.browser.AistudioBrowser.__aenter__", mock_enter),
        patch("unsafie.aistudio.browser.AistudioBrowser.monopolize_tabs", AsyncMock()),
        patch("unsafie.aistudio.browser.AistudioBrowser.check_welcome_page", mock_check_welcome),
        patch("unsafie.aistudio.browser.AistudioBrowser.close", AsyncMock()),
    ):
        await pool.start()

        assert pool.is_ready() is True
        assert len(pool._managed) == 1
        assert "normal-profile" in pool._managed
        assert "welcome-profile" not in pool._managed
