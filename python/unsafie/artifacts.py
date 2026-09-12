from unsafie.log import get_logger
from uuid import UUID

from unsafie.database import SessionLocal
from unsafie.database.models.artifact import Artifact
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.artifact import ArtifactRepository
from unsafie.settings import settings

logger = get_logger(__name__)


def url(slug: str) -> str:
    return f"{settings.artifact_origin}/{slug}"


async def publish(
    *,
    content: str,
    title: str | None = None,
    bot_id: int | None = None,
    chat_id: int | None = None,
    turn_id: UUID | None = None,
) -> Artifact | None:
    async with SessionLocal() as session:
        return await ArtifactRepository(session).markdown(
            content=content, title=title, bot_id=bot_id, chat_id=chat_id, turn_id=turn_id,
        )


async def for_turn(turn: Turn) -> str | None:
    async with SessionLocal() as session:
        artifact = await ArtifactRepository(session).for_turn(
            turn_id=turn.id, bot_id=turn.bot_id, chat_id=turn.chat_id,
        )
    return artifact.slug if artifact is not None else None


async def of_turn(turn_id: UUID) -> str | None:
    async with SessionLocal() as session:
        artifact = await ArtifactRepository(session).of_turn(turn_id)
    return artifact.slug if artifact is not None else None


async def telemetry_for_turn(turn: Turn) -> str | None:
    async with SessionLocal() as session:
        artifact = await ArtifactRepository(session).for_telemetry(
            turn_id=turn.id, bot_id=turn.bot_id, chat_id=turn.chat_id,
        )
    return artifact.slug if artifact is not None else None


async def telemetry_of_turn(turn_id: UUID) -> str | None:
    async with SessionLocal() as session:
        artifact = await ArtifactRepository(session).of_telemetry(turn_id)
    return artifact.slug if artifact is not None else None


async def telemetry_for_turn(
    turn_id: UUID, bot_id: int | None = None, chat_id: int | None = None
) -> str | None:
    async with SessionLocal() as session:
        artifact = await ArtifactRepository(session).for_telemetry(
            turn_id=turn_id, bot_id=bot_id, chat_id=chat_id,
        )
    return artifact.slug if artifact is not None else None


async def of_telemetry(turn_id: UUID) -> str | None:
    async with SessionLocal() as session:
        artifact = await ArtifactRepository(session).telemetry_of_turn(turn_id)
    return artifact.slug if artifact is not None else None
