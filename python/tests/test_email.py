from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from unsafie.api.routes.cli.email import (
    _extract_code,
    _extract_emails,
    _lookup_code,
    get_email_code_path,
    get_email_code_query,
    receive_email,
)
from unsafie.cli.email import get_code
from unsafie.settings import settings


def test_extract_code() -> None:
    assert _extract_code("Your verification code is 849201.") == "849201"
    assert _extract_code("Код подтверждения: 123456") == "123456"
    assert _extract_code("849201 is your code") == "849201"
    assert _extract_code("Single match 654321 in text") == "654321"
    assert _extract_code("Only 5 digits 12345 and 7 digits 1234567") is None
    assert _extract_code("No numbers here") is None


def test_extract_emails() -> None:
    assert _extract_emails("user@example.com") == ["user@example.com"]
    assert _extract_emails("User Name <user@example.com>") == ["user@example.com"]
    assert _extract_emails(["A@example.com", "b@example.com"]) == ["a@example.com", "b@example.com"]
    assert _extract_emails("invalid") == []
    assert _extract_emails(None) == []


@pytest.mark.anyio
async def test_receive_email_forbidden() -> None:
    req = MagicMock(spec=Request)
    with patch.object(settings, "email_webhook_secret", "correct_secret"), pytest.raises(HTTPException) as exc_info:
        await receive_email("wrong_secret", req)
    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_receive_email_json_success() -> None:
    req = AsyncMock(spec=Request)
    req.body = AsyncMock(return_value=b"{}")
    req.json = AsyncMock(
        return_value={
            "to": "srnttrsntrsut@unsafie.com",
            "subject": "Verification",
            "text": "Your code is 654321",
        }
    )

    mock_redis = AsyncMock()
    with patch.object(settings, "email_webhook_secret", "test_secret"), patch("unsafie.cluster.client", return_value=mock_redis):
        res = await receive_email("test_secret", req)
        assert res["ok"] is True
        assert res["code"] == "654321"
        assert "srnttrsntrsut@unsafie.com" in res["recipients"]
        mock_redis.set.assert_called_once()


@pytest.mark.anyio
async def test_lookup_code_existing() -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "849201"
    with patch("unsafie.cluster.client", return_value=mock_redis):
        res = await _lookup_code("srnttrsntrsut@unsafie.com")
        assert res["ok"] is True
        assert res["code"] == "849201"


@pytest.mark.anyio
async def test_lookup_code_missing() -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    with patch("unsafie.cluster.client", return_value=mock_redis):
        res = await _lookup_code("unknown@unsafie.com")
        assert res["ok"] is True
        assert res["code"] == "0"


@pytest.mark.anyio
async def test_get_email_code_endpoints() -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "112233"
    with patch("unsafie.cluster.client", return_value=mock_redis):
        q_res = await get_email_code_query(email="test@unsafie.com")
        assert q_res["code"] == "112233"
        p_res = await get_email_code_path(address="test@unsafie.com")
        assert p_res["code"] == "112233"


def test_cli_get_code() -> None:
    mock_cli = MagicMock()
    mock_cli.call.return_value = {"ok": True, "code": "987654"}
    with patch("unsafie.cli.email.client", return_value=mock_cli):
        assert get_code("foo@unsafie.com") == "987654"

    mock_cli.call.return_value = {"ok": True, "code": "0"}
    with patch("unsafie.cli.email.client", return_value=mock_cli):
        assert get_code("bar@unsafie.com") == "0"
