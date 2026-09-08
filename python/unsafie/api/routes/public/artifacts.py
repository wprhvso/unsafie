import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from unsafie.api import static
from unsafie.database import SessionLocal
from unsafie.database.models.artifact import ArtifactKind
from unsafie.database.repositories.artifact import ArtifactRepository
from unsafie.slugs import is_slug

logger = logging.getLogger(__name__)

router = APIRouter(tags=["artifacts"])

RESERVED = ("api/", "gh/", "_app/", "health", "docs", "redoc", "openapi.json")
MACHINERY = ("api/", "gh/")
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    return HTMLResponse(static.render(None))


@router.api_route("/{path:path}", methods=METHODS, include_in_schema=False)
async def spa(path: str, request: Request):
    if path.startswith(MACHINERY):
        logger.info("no route %s /%s", request.method, path)
        return JSONResponse({"detail": f"no route {request.method} /{path}"}, status_code=404)
    if request.method not in ("GET", "HEAD"):
        raise HTTPException(405, f"{request.method} is not accepted here")
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
