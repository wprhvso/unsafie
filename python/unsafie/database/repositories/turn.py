import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.response import Response
from unsafie.database.models.turn import Turn, TurnStatus
from unsafie.database.models.update import Update

logger = logging.getLogger(__name__)

OWNER_QUERY = text("""
    SELECT COALESCE(
        (
            SELECT r.turn_id
            FROM responses r
            WHERE r.bot_id = :bot_id
              AND r.chat_id = :chat_id
              AND r.turn_id IS NOT NULL
              AND r.message_ids @> jsonb_build_array(CAST(:message_id AS bigint))
            ORDER BY r.created_at DESC
            LIMIT 1
        ),
        (
            SELECT u.turn_id
            FROM updates u
            WHERE u.bot_id = :bot_id
              AND u.chat_id = :chat_id
              AND u.message_id = :message_id
              AND u.turn_id IS NOT NULL
            ORDER BY u.created_at DESC, u.id DESC
            LIMIT 1
        )
    ) AS turn_id
""")

REPLY_QUERY = text("""
    WITH RECURSIVE lineage AS (
        SELECT id, parent_id, 0 AS depth
        FROM turns
        WHERE id = CAST(:turn_id AS uuid)
        UNION ALL
        SELECT t.id, t.parent_id, l.depth + 1
        FROM lineage l
        JOIN turns t ON t.id = l.parent_id
        WHERE l.depth < CAST(:max_depth AS integer)
    ),
    last_in AS (
        SELECT max(message_id) AS id
        FROM updates
        WHERE bot_id = :bot_id AND chat_id = :chat_id
    ),
    last_out AS (
        SELECT max(CAST(elem AS bigint)) AS id
        FROM responses r, jsonb_array_elements_text(r.message_ids) AS elem
        WHERE r.bot_id = :bot_id AND r.chat_id = :chat_id
    ),
    last_msg AS (
        SELECT GREATEST(
            COALESCE((SELECT id FROM last_in), 0),
            COALESCE((SELECT id FROM last_out), 0)
        ) AS id
    )
    SELECT
        (SELECT id FROM last_msg) AS last_id,
        EXISTS (
            SELECT 1 FROM updates u
            WHERE u.bot_id = :bot_id AND u.chat_id = :chat_id
              AND u.message_id = (SELECT id FROM last_msg)
              AND u.turn_id IN (SELECT id FROM lineage)
        ) OR EXISTS (
            SELECT 1 FROM responses r
            WHERE r.bot_id = :bot_id AND r.chat_id = :chat_id
              AND r.turn_id IN (SELECT id FROM lineage)
              AND r.message_ids @> jsonb_build_array((SELECT id FROM last_msg))
        ) AS in_lineage
""")


class TurnRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, turn_id: UUID) -> Turn | None:
        return await self.session.get(Turn, turn_id)

    async def owner(self, bot_id: int, chat_id: int, message_id: int) -> Turn | None:
        turn_id = await self.session.scalar(
            OWNER_QUERY, {"bot_id": bot_id, "chat_id": chat_id, "message_id": message_id}
        )
        if turn_id is None:
            return None
        return await self.session.get(Turn, turn_id)

    async def is_session_head(self, turn: Turn) -> bool:
        if turn.session_id is None:
            return False
        later = await self.session.scalar(
            select(func.count())
            .select_from(Turn)
            .where(
                Turn.bot_id == turn.bot_id,
                Turn.chat_id == turn.chat_id,
                Turn.session_id == turn.session_id,
                Turn.id != turn.id,
                Turn.created_at >= turn.created_at,
            )
        )
        return not later

    async def create(
        self,
        *,
        bot_id: int,
        chat_id: int,
        user_id: int,
        parent: Turn | None,
        reply_to: int | None,
        session_id: str | None,
        forked: bool,
    ) -> Turn:
        turn = Turn(
            bot_id=bot_id,
            chat_id=chat_id,
            user_id=user_id,
            parent_id=parent.id if parent else None,
            reply_to=reply_to,
            session_id=session_id,
            forked=forked,
            status=TurnStatus.RUNNING,
        )
        self.session.add(turn)
        await self.session.commit()
        await self.session.refresh(turn)
        logger.info(
            "bot=%s chat=%s turn=%s created parent=%s session=%s forked=%s",
            bot_id,
            chat_id,
            turn.id,
            turn.parent_id,
            session_id,
            forked,
        )
        return turn

    async def set_session(self, turn_id: UUID, session_id: str) -> None:
        turn = await self.session.get(Turn, turn_id)
        if turn is None or turn.session_id == session_id:
            return
        turn.session_id = session_id
        await self.session.commit()

    async def record(
        self,
        turn_id: UUID,
        *,
        credential_id: int | None,
        cost_usd: float | None,
        charge: int,
        num_turns: int,
        result: str | None,
    ) -> None:
        turn = await self.session.get(Turn, turn_id)
        if turn is None:
            return
        if credential_id is not None:
            turn.credential_id = credential_id
        if cost_usd is not None:
            turn.cost_usd = (turn.cost_usd or 0.0) + cost_usd
        turn.charge += charge
        turn.num_turns += num_turns
        if result:
            turn.result = result
        await self.session.commit()

    async def finish(self, turn_id: UUID, status: TurnStatus, note: str | None = None) -> None:
        turn = await self.session.get(Turn, turn_id)
        if turn is None:
            return
        turn.status = status
        turn.finished_at = datetime.now(UTC)
        if note:
            turn.result = note
        await self.session.commit()
        logger.info("turn=%s finished status=%s", turn_id, status)

    async def reply_target(self, turn: Turn, max_depth: int) -> int | None:
        row = (
            await self.session.execute(
                REPLY_QUERY,
                {
                    "turn_id": turn.id,
                    "bot_id": turn.bot_id,
                    "chat_id": turn.chat_id,
                    "max_depth": max_depth,
                },
            )
        ).one()
        if row.in_lineage:
            return None
        last = await self.session.scalar(
            select(Update.message_id)
            .where(Update.turn_id == turn.id, Update.message_id.is_not(None))
            .order_by(Update.ordinal.desc())
            .limit(1)
        )
        return int(last) if last is not None else None

    async def responses(self, turn_id: UUID) -> list[Response]:
        rows = await self.session.scalars(
            select(Response).where(Response.turn_id == turn_id).order_by(Response.created_at)
        )
        return list(rows)

    async def page(
        self,
        offset: int = 0,
        limit: int = 50,
        bot_id: int | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
        status: str | None = None,
    ) -> tuple[list[Turn], int]:
        cond = []
        if bot_id is not None:
            cond.append(Turn.bot_id == bot_id)
        if chat_id is not None:
            cond.append(Turn.chat_id == chat_id)
        if user_id is not None:
            cond.append(Turn.user_id == user_id)
        if status is not None:
            cond.append(Turn.status == status)
        total = await self.session.scalar(select(func.count()).select_from(Turn).where(*cond)) or 0
        rows = await self.session.scalars(
            select(Turn).where(*cond).order_by(Turn.created_at.desc()).offset(offset).limit(limit)
        )
        return list(rows), int(total)

    async def children(self, turn_id: UUID) -> list[Turn]:
        rows = await self.session.scalars(
            select(Turn).where(Turn.parent_id == turn_id).order_by(Turn.created_at)
        )
        return list(rows)

    async def mark_stale_running(self) -> int:
        rows = list(
            await self.session.scalars(select(Turn).where(Turn.status == TurnStatus.RUNNING))
        )
        for turn in rows:
            turn.status = TurnStatus.FAILED
            turn.finished_at = datetime.now(UTC)
            turn.result = turn.result or "interrupted by restart"
        await self.session.commit()
        return len(rows)
