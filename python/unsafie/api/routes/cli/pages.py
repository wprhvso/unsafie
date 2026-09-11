import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from unsafie import artifacts
from unsafie.api.routes.cli.deps import Pages
from unsafie.database import SessionLocal
from unsafie.database.models.artifact import ArtifactKind
from unsafie.database.repositories.artifact import ArtifactRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pages", tags=["cli"])

TITLE_LIMIT = 200


class Page(BaseModel):
    content: str = Field(min_length=1)
    title: str | None = None
    turn: str | None = None


def _view(slug: str, title: str | None, created: object = None) -> dict:
    return {"slug": slug, "title": title, "url": artifacts.url(slug), "created_at": created}


@router.post("")
async def create(body: Page, who: Pages) -> dict:
    if who.chat_id is None:
        raise HTTPException(400, "no chat: this token is not bound to a chat")
    turn = await who.turn(body.turn)
    artifact = await artifacts.publish(
        content=body.content,
        title=(body.title or "").strip()[:TITLE_LIMIT] or None,
        bot_id=who.bot_id,
        chat_id=who.chat_id,
        turn_id=turn.id if turn else None,
    )
    if artifact is None:
        raise HTTPException(503, "no free link could be allocated, try again")
    logger.info("%s published %s (%s chars)", who.prefix, artifact.slug, len(body.content))
    return _view(artifact.slug, artifact.title, artifact.created_at)


@router.get("")
async def listing(who: Pages, limit: int = 20) -> list[dict]:
    if who.chat_id is None:
        raise HTTPException(400, "no chat: this token is not bound to a chat")
    async with SessionLocal() as session:
        rows = await ArtifactRepository(session).for_chat(
            who.chat_id, kind=ArtifactKind.MARKDOWN, limit=min(max(limit, 1), 100),
        )
    return [_view(row.slug, row.title, row.created_at) for row in rows]


@router.get("/{slug}")
async def read(slug: str, who: Pages) -> dict:
    if who.chat_id is None:
        raise HTTPException(400, "no chat: this token is not bound to a chat")
    async with SessionLocal() as session:
        repo = ArtifactRepository(session)
        artifact = await repo.by_slug(slug)
        if artifact is None or artifact.chat_id != who.chat_id:
            raise HTTPException(404, "no such page")
        return {
            "slug": artifact.slug,
            "title": artifact.title,
            "content": artifact.content or "",
            "url": artifacts.url(artifact.slug),
            "created_at": artifact.created_at,
        }


@router.put("/{slug}")
async def replace(slug: str, body: Page, who: Pages) -> dict:
    if who.chat_id is None:
        raise HTTPException(400, "no chat: this token is not bound to a chat")
    async with SessionLocal() as session:
        repo = ArtifactRepository(session)
        artifact = await repo.by_slug(slug)
        if artifact is None or artifact.chat_id != who.chat_id:
            raise HTTPException(404, "no such page")
        if artifact.kind != ArtifactKind.MARKDOWN:
            raise HTTPException(400, "only markdown pages can be modified")
        artifact.content = body.content
        if body.title is not None:
            artifact.title = body.title.strip()[:TITLE_LIMIT] or None
        await session.commit()
        return _view(artifact.slug, artifact.title, artifact.created_at)


@router.delete("/{slug}")
async def drop(slug: str, who: Pages) -> dict:
    if who.chat_id is None:
        raise HTTPException(400, "no chat: this token is not bound to a chat")
    async with SessionLocal() as session:
        repo = ArtifactRepository(session)
        artifact = await repo.by_slug(slug)
        if artifact is None or artifact.chat_id != who.chat_id:
            raise HTTPException(404, "no such page")
        if artifact.kind != ArtifactKind.MARKDOWN:
            raise HTTPException(400, "only markdown pages can be deleted")
        await repo.delete(slug)
    return {"deleted": slug}
