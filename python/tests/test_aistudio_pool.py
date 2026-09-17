from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from unsafie.aistudio.pool import AistudioPoolManager


@pytest.mark.anyio
async def test_pool_discards_faulty_profile_on_start() -> None:
    pool = AistudioPoolManager(endpoint="http://mock:5050", max_active_profiles=3)
    profiles = [
        {"id": "bad-profile-1", "name": "Broken", "tags": ["aistudio-api"]},
        {"id": "good-profile-2", "name": "Working", "tags": ["aistudio-api"]},
    ]

    async def mock_enter(self_browser):
        if self_browser.profile["id"] == "bad-profile-1":
            raise RuntimeError("Failed to launch browser: Service Unavailable (503)")
        return self_browser

    with (
        patch.object(pool, "load_profiles", AsyncMock(return_value=profiles)),
        patch("unsafie.aistudio.browser.AistudioBrowser.__aenter__", mock_enter),
        patch("unsafie.aistudio.browser.AistudioBrowser.monopolize_tabs", AsyncMock()),
        patch("unsafie.aistudio.browser.AistudioBrowser.__aexit__", AsyncMock()),
    ):
        await pool.start()

        assert pool.is_ready() is True
        assert len(pool._managed) == 1
        assert "good-profile-2" in pool._managed
        assert "bad-profile-1" not in pool._managed


@pytest.mark.anyio
async def test_pool_fails_if_all_profiles_broken() -> None:
    pool = AistudioPoolManager(endpoint="http://mock:5050", max_active_profiles=2)
    profiles = [
        {"id": "bad-1", "tags": ["aistudio-api"]},
        {"id": "bad-2", "tags": ["aistudio-api"]},
    ]

    async def mock_enter(self_browser):
        raise RuntimeError("Crash on start")

    with (
        patch.object(pool, "load_profiles", AsyncMock(return_value=profiles)),
        patch("unsafie.aistudio.browser.AistudioBrowser.__aenter__", mock_enter),
        patch("unsafie.aistudio.browser.AistudioBrowser.__aexit__", AsyncMock()),
        pytest.raises(RuntimeError, match="No healthy browser profiles"),
    ):
        await pool.start()

        assert pool.is_ready() is False
        assert len(pool._managed) == 0
