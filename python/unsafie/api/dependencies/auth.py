import base64
import hashlib
import hmac
import logging
import secrets
import time

from fastapi import HTTPException, Request

from unsafie.settings import settings

logger = logging.getLogger(__name__)

COOKIE = "unsafie_admin"


def _sign(payload: str) -> str:
    return hmac.new(settings.admin_token.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue() -> str:
    expires = int(time.time()) + settings.admin_session_days * 86400
    payload = f"admin.{expires}"
    return base64.urlsafe_b64encode(f"{payload}.{_sign(payload)}".encode()).decode().rstrip("=")


def verify(cookie: str | None) -> bool:
    if not cookie or not settings.admin_token:
        return False
    try:
        raw = base64.urlsafe_b64decode(cookie + "=" * (-len(cookie) % 4)).decode()
        subject, expires, signature = raw.rsplit(".", 2)
    except (ValueError, UnicodeDecodeError):
        return False
    if subject != "admin" or not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(_sign(f"{subject}.{expires}"), signature)


def check_token(token: str) -> bool:
    if not settings.admin_token:
        return False
    return secrets.compare_digest(token.strip(), settings.admin_token)


async def admin_required(request: Request) -> None:
    if not settings.admin_token:
        raise HTTPException(503, "ADMIN_TOKEN is not configured on the server")
    if not verify(request.cookies.get(COOKIE)):
        raise HTTPException(401, "not authenticated")
