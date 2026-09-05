import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from unsafie.api import static
from unsafie.database import SessionLocal
from unsafie.database.repositories.share import ShareRepository
from unsafie.slugs import is_slug

logger = logging.getLogger(__name__)

router = APIRouter(tags=["share"])

RESERVED = ("api/", "gh/", "_app/", "health", "docs", "redoc", "openapi.json")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    return HTMLResponse(static.render(None))


@router.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa(path: str):
    """A share link, or any client-side route of the admin app.

    nginx normally serves the bundle itself; this keeps the app usable without it.
    """
    if path.startswith(RESERVED):
        raise HTTPException(404, "Not Found")
    slug = path.rstrip("/")
    if not is_slug(slug):
        return HTMLResponse(static.render(None))
    async with SessionLocal() as session:
        content = await ShareRepository(session).content(slug)
    if content is None:
        return HTMLResponse(static.not_found(slug), status_code=404)
    return HTMLResponse(static.render({"slug": slug, "content": content}))
