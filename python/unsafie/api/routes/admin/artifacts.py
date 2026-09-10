from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from unsafie import artifacts
from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import ArtifactRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.artifact import ArtifactRepository

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("", response_model=Page[ArtifactRead])
async def list_artifacts(params: Annotated[PageParams, Depends(paging)]):
    async with SessionLocal() as session:
        rows, total = await ArtifactRepository(session).page(params.offset, params.limit)
    items = [
        ArtifactRead(
            id=r.id,
            slug=r.slug,
            kind=r.kind,
            title=r.title,
            url=artifacts.url(r.slug),
            bytes=len(r.content or ""),
            chat_id=r.chat_id,
            turn_id=r.turn_id,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return Page.of(items, total, params)


@router.delete("/{slug}", status_code=204)
async def delete_artifact(slug: str) -> None:
    async with SessionLocal() as session:
        if not await ArtifactRepository(session).delete(slug):
            raise HTTPException(404, "no such artifact")
