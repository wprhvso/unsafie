import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from unsafie import artifacts
from unsafie.agent import live
from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import ResponseRead, TurnDetail, TurnRead
from unsafie.database import SessionLocal
from unsafie.database.models.turn_message import TurnMessages
from unsafie.database.repositories.turn import TurnRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/turns", tags=["turns"])


@router.get("", response_model=Page[TurnRead])
async def list_turns(
    params: Annotated[PageParams, Depends(paging)],
    bot_id: int | None = None,
    chat_id: int | None = None,
    user_id: int | None = None,
    status: str | None = None,
):
    async with SessionLocal() as session:
        rows, total = await TurnRepository(session).page(
            params.offset, params.limit, bot_id, chat_id, user_id, status,
        )
    return Page.of([TurnRead.model_validate(r) for r in rows], total, params)


@router.get("/{turn_id}/live")
async def live_link(turn_id: UUID):
    try:
        token = await live.token_of(turn_id)
    except Exception as e:
        logger.warning("turn=%s live token unreadable: %s", turn_id, e)
        token = None
    return {"token": token, "url": artifacts.url(token) if token else None}


@router.get("/{turn_id}", response_model=TurnDetail)
async def get_turn(turn_id: UUID):
    async with SessionLocal() as session:
        repo = TurnRepository(session)
        turn = await repo.get(turn_id)
        if turn is None:
            raise HTTPException(404, "no such turn")
        parent = await repo.get(turn.parent_id) if turn.parent_id else None
        children = await repo.children(turn_id)
        conversation = await repo.conversation(turn.root_id)
        responses = await repo.responses(turn_id)
        segment = await session.get(TurnMessages, turn_id)
    return TurnDetail(
        turn=TurnRead.model_validate(turn),
        parent=TurnRead.model_validate(parent) if parent else None,
        children=[TurnRead.model_validate(c) for c in children],
        conversation=[TurnRead.model_validate(c) for c in conversation],
        responses=[ResponseRead.model_validate(r) for r in responses],
        messages=segment.count if segment else 0,
    )
