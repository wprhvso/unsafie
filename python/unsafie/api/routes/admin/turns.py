from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import ResponseRead, TurnDetail, TurnRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.turn import TurnRepository

router = APIRouter(prefix="/turns", tags=["turns"])


@router.get("", response_model=Page[TurnRead])
async def list_turns(
    bot_id: int | None = None,
    chat_id: int | None = None,
    user_id: int | None = None,
    status: str | None = None,
    params: PageParams = Depends(paging),
):
    async with SessionLocal() as session:
        rows, total = await TurnRepository(session).page(
            params.offset, params.limit, bot_id, chat_id, user_id, status
        )
    return Page.of([TurnRead.model_validate(r) for r in rows], total, params)


@router.get("/{turn_id}", response_model=TurnDetail)
async def get_turn(turn_id: UUID):
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        turn = await repo.get(turn_id)
        if turn is None:
            raise HTTPException(404, "no such turn")
        parent = await repo.get(turn.parent_id) if turn.parent_id else None
        children = await repo.children(turn_id)
        responses = await repo.responses(turn_id)
    return TurnDetail(
        turn=TurnRead.model_validate(turn),
        parent=TurnRead.model_validate(parent) if parent else None,
        children=[TurnRead.model_validate(c) for c in children],
        responses=[ResponseRead.model_validate(r) for r in responses],
    )
