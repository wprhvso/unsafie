import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from unsafie.api import static
from unsafie.database import SessionLocal
from unsafie.database.models.artifact import ArtifactKind
from unsafie.database.repositories.artifact import ArtifactRepository
from unsafie.slugs import is_slug

logger = logging.getLogger(__name__)

router = APIRouter(tags=["artifacts"])

RESERVED = ("api/", "gh/", "_app/", "health", "docs", "redoc", "openapi.json")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    return HTMLResponse(static.render(None))


@router.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa(path: str):
    if path.startswith(RESERVED):
        raise HTTPException(404, "Not Found")
    slug = path.rstrip("/")
    if not is_slug(slug):
        return HTMLResponse(static.render(None))
    async with SessionLocal() as session:
        artifact = await ArtifactRepository(session).by_slug(slug)
    if artifact is None:
        return HTMLResponse(static.not_found(slug), status_code=404)
    payload = {"slug": slug, "kind": artifact.kind, "title": artifact.title}
    if artifact.kind == ArtifactKind.MARKDOWN:
        payload["content"] = artifact.content or ""
    return HTMLResponse(static.render(payload))
