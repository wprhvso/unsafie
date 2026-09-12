import contextlib
import email
import hmac
import re
from email.policy import default
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from unsafie import cluster
from unsafie.settings import settings

router = APIRouter(prefix="/email", tags=["cli"])

PATTERNS = (
    re.compile(r"(?i)(?:code|verification|passcode|pin|otp|парол\w*|код|подтвержден\w*)[^\d\n]{0,30}?\b(\d{6})\b"),
    re.compile(r"\b(\d{6})\b[^\d\n]{0,30}?(?:is your|это ваш|твой код|code)"),
    re.compile(r"\b(\d{6})\b"),
)


def _extract_emails(raw_to: Any) -> list[str]:
    if not raw_to:
        return []
    items = raw_to if isinstance(raw_to, list) else [raw_to]
    found = []
    for item in items:
        for match in re.findall(r"[\w\.\+\-]+@[\w\.\-]+", str(item)):
            found.append(match.lower())
    return list(dict.fromkeys(found))


def _extract_code(text: str) -> str | None:
    for pattern in PATTERNS:
        if match := pattern.search(text):
            return match.group(1) if match.groups() else match.group(0)
    return None


@router.post("/{secret}")
async def receive_email(secret: str, request: Request) -> dict:
    if not settings.email_webhook_secret or not hmac.compare_digest(secret, settings.email_webhook_secret):
        raise HTTPException(403, "forbidden")

    raw_bytes = await request.body()
    data: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        data = await request.json()

    to_addrs = _extract_emails(data.get("to") or data.get("recipient") or data.get("rcpt"))

    search_parts = [
        str(data.get("subject") or ""),
        str(data.get("text") or ""),
        str(data.get("html") or ""),
        str(data.get("body") or ""),
    ]

    raw_mime = data.get("raw")
    if isinstance(raw_mime, str):
        search_parts.append(raw_mime)
        with contextlib.suppress(Exception):
            parsed_msg = email.message_from_bytes(raw_mime.encode("utf-8", errors="replace"), policy=default)
            if not to_addrs:
                to_addrs = _extract_emails(parsed_msg.get("to"))
            if body_part := parsed_msg.get_body(preferencelist=("plain", "html")):
                search_parts.append(str(body_part.get_content()))
    elif raw_bytes:
        try:
            parsed_msg = email.message_from_bytes(raw_bytes, policy=default)
            if not to_addrs:
                to_addrs = _extract_emails(parsed_msg.get("to"))
            if subj := parsed_msg.get("subject"):
                search_parts.append(str(subj))
            if body_part := parsed_msg.get_body(preferencelist=("plain", "html")):
                search_parts.append(str(body_part.get_content()))
            search_parts.append(raw_bytes.decode("utf-8", errors="replace"))
        except Exception:
            search_parts.append(raw_bytes.decode("utf-8", errors="replace"))

    combined_text = "\n".join(search_parts)
    code = _extract_code(combined_text)

    if code and to_addrs:
        r = cluster.client()
        for addr in to_addrs:
            await r.set(cluster.key("email", "code", addr), code)

    return {"ok": True, "code": code, "recipients": to_addrs}


@router.get("/code")
async def get_email_code_query(email: Annotated[str, Query()]) -> dict:
    return await _lookup_code(email)


@router.get("/{address:path}")
async def get_email_code_path(address: str) -> dict:
    return await _lookup_code(address)


async def _lookup_code(address: str) -> dict:
    matches = _extract_emails(address)
    norm = matches[0] if matches else address.strip().lower()
    r = cluster.client()
    val = await r.get(cluster.key("email", "code", norm))
    if isinstance(val, bytes):
        val = val.decode()
    return {"ok": True, "email": norm, "code": val or "0"}
