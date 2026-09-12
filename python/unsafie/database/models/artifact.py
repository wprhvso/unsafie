from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base
from unsafie.slugs import SLUG_LENGTH


class ArtifactKind(StrEnum):
    MARKDOWN = "markdown"
    TURN = "turn"
    TELEMETRY = "telemetry"
    TELEMETRY = "telemetry"


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_chat", "bot_id", "chat_id", "created_at"),
        Index("ix_artifacts_turn", "turn_id", unique=True, postgresql_where=text("kind = 'turn'")),
        Index("ix_artifacts_turn_telemetry", "turn_id", unique=True, postgresql_where=text("kind = 'telemetry'")),
        Index("ix_artifacts_telemetry", "turn_id", unique=True, postgresql_where=text("kind = 'telemetry'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(SLUG_LENGTH), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default=ArtifactKind.MARKDOWN)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_id: Mapped[int | None] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), nullable=True,
    )
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    turn_id: Mapped[UUID | None] = mapped_column(
        SQL_UUID(as_uuid=True), ForeignKey("turns.id", ondelete="CASCADE"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
