import logging

from fastapi import APIRouter, HTTPException, Request, Response

from unsafie.api.dependencies.auth import COOKIE, check_token, issue, verify
from unsafie.api.schemas.common import Ok
from unsafie.api.schemas.models import LoginWrite
from unsafie.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login", response_model=Ok)
async def login(body: LoginWrite, response: Response):
    if not settings.admin_token:
        raise HTTPException(503, "ADMIN_TOKEN is not configured on the server")
    if not check_token(body.token):
        logger.warning("admin login failed")
        raise HTTPException(401, "wrong token")
    response.set_cookie(
        COOKIE,
        issue(),
        max_age=settings.admin_session_days * 86400,
        httponly=True,
        secure=settings.public_origin.startswith("https"),
        samesite="lax",
        path="/",
    )
    logger.info("admin logged in")
    return Ok(detail="signed in")


@router.post("/logout", response_model=Ok)
async def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return Ok(detail="signed out")


@router.get("/session", response_model=Ok)
async def session(request: Request):
    ok = verify(request.cookies.get(COOKIE))
    return Ok(ok=ok, detail="signed in" if ok else "not signed in")
