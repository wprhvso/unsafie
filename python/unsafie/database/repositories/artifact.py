from unsafie.log import get_logger
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.artifact import Artifact, ArtifactKind
from unsafie.slugs import generate_slug

logger = get_logger(__name__)

ATTEMPTS = 16


class ArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_slug(self, slug: str) -> Artifact | None:
        return await self.session.scalar(select(Artifact).where(Artifact.slug == slug))

    async def of_turn(self, turn_id: UUID) -> Artifact | None:
        return await self.session.scalar(
            select(Artifact).where(Artifact.turn_id == turn_id, Artifact.kind == ArtifactKind.TURN),
        )

    async def telemetry_of_turn(self, turn_id: UUID) -> Artifact | None:
        return await self.session.scalar(
            select(Artifact).where(Artifact.turn_id == turn_id, Artifact.kind == ArtifactKind.TELEMETRY),
        )

    async def of_telemetry(self, turn_id: UUID) -> Artifact | None:
        return await self.session.scalar(
            select(Artifact).where(Artifact.turn_id == turn_id, Artifact.kind == ArtifactKind.TELEMETRY),
        )

    async def _add(self, **fields) -> Artifact | None:
        for _ in range(ATTEMPTS):
            artifact = Artifact(slug=generate_slug(), **fields)
            self.session.add(artifact)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                taken = fields.get("turn_id")
                if fields.get("kind") == ArtifactKind.TURN and taken is not None:
                    existing = await self.of_turn(taken)
                    if existing is not None:
                        return existing
                if fields.get("kind") == ArtifactKind.TELEMETRY and taken is not None:
                    existing = await self.telemetry_of_turn(taken)
                    if existing is not None:
                        return existing
                if fields.get("kind") == ArtifactKind.TELEMETRY and taken is not None:
                    existing = await self.of_telemetry(taken)
                    if existing is not None:
                        return existing
                continue
            logger.info(
                "artifact %s kind=%s chat=%s turn=%s created",
                artifact.slug,
                artifact.kind,
                artifact.chat_id,
                artifact.turn_id,
            )
            return artifact
        return None

    async def markdown(
        self,
        *,
        content: str,
        title: str | None,
        bot_id: int | None,
        chat_id: int | None,
        turn_id: UUID | None,
    ) -> Artifact | None:
        return await self._add(
            kind=ArtifactKind.MARKDOWN,
            content=content,
            title=title,
            bot_id=bot_id,
            chat_id=chat_id,
            turn_id=turn_id,
        )

    async def for_turn(self, *, turn_id: UUID, bot_id: int, chat_id: int) -> Artifact | None:
        existing = await self.of_turn(turn_id)
        if existing is not None:
            return existing
        return await self._add(
            kind=ArtifactKind.TURN, turn_id=turn_id, bot_id=bot_id, chat_id=chat_id,
        )

    async def for_telemetry(
        self, *, turn_id: UUID, bot_id: int | None = None, chat_id: int | None = None
    ) -> Artifact | None:
        existing = await self.telemetry_of_turn(turn_id)
        if existing is not None:
            return existing
        return await self._add(
            kind=ArtifactKind.TELEMETRY, turn_id=turn_id, bot_id=bot_id, chat_id=chat_id,
        )

    async def for_telemetry(self, *, turn_id: UUID, bot_id: int | None = None, chat_id: int | None = None) -> Artifact | None:
        existing = await self.of_telemetry(turn_id)
        if existing is not None:
            return existing
        return await self._add(
            kind=ArtifactKind.TELEMETRY, turn_id=turn_id, bot_id=bot_id, chat_id=chat_id,
        )

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[Artifact], int]:
        total = await self.session.scalar(select(func.count()).select_from(Artifact)) or 0
        rows = await self.session.scalars(
            select(Artifact).order_by(Artifact.id.desc()).offset(offset).limit(limit),
        )
        return list(rows), int(total)

    async def for_chat(
        self,
        chat_id: int | None,
        kind: ArtifactKind = ArtifactKind.MARKDOWN,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Artifact]:
        if chat_id is None:
            return []
        query = select(Artifact).where(Artifact.kind == kind, Artifact.chat_id == chat_id)
        rows = await self.session.scalars(
            query.order_by(Artifact.id.desc()).offset(offset).limit(limit),
        )
        return list(rows)

    async def delete(self, slug: str) -> bool:
        row = await self.by_slug(slug)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True
