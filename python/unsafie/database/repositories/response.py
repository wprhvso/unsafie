import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.response import Response, ResponseKind

logger = logging.getLogger(__name__)


class ResponseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        *,
        bot_id: int,
        chat_id: int,
        turn_id: UUID | None,
        kind: ResponseKind,
        content: str,
        message_ids: list[int],
        reply_to: int | None,
    ) -> Response:
        response = Response(
            bot_id=bot_id,
            chat_id=chat_id,
            turn_id=turn_id,
            kind=kind,
            content=content,
            message_ids=list(message_ids),
            reply_to=reply_to,
        )
        self.session.add(response)
        await self.session.commit()
        return response

    async def get(self, response_id: UUID) -> Response | None:
        return await self.session.get(Response, response_id)

    async def by_message(self, bot_id: int, chat_id: int, message_id: int) -> Response | None:
        return await self.session.scalar(
            select(Response)
            .where(
                Response.bot_id == bot_id,
                Response.chat_id == chat_id,
                Response.message_ids.op("@>")(func.jsonb_build_array(message_id)),
            )
            .order_by(Response.created_at.desc())
            .limit(1)
        )

    async def set_content(
        self, bot_id: int, chat_id: int, message_id: int, content: str
    ) -> Response | None:
        response = await self.by_message(bot_id, chat_id, message_id)
        if response is None or len(response.message_ids) != 1:
            return response
        response.content = content
        await self.session.commit()
        return response

    async def forget(self, bot_id: int, chat_id: int, message_id: int) -> Response | None:
        response = await self.by_message(bot_id, chat_id, message_id)
        if response is None:
            return None
        response.message_ids = [i for i in response.message_ids if i != message_id]
        await self.session.commit()
        return response
