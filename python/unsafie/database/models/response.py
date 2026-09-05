import uuid
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class ResponseKind(StrEnum):
    AGENT = "agent"
    SYSTEM = "system"


class Response(Base):
    __tablename__ = "responses"
    __table_args__ = (
        Index("ix_responses_chat", "bot_id", "chat_id", "created_at"),
        Index("ix_responses_message_ids", "message_ids", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(SQL_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    turn_id: Mapped[UUID | None] = mapped_column(
        SQL_UUID(as_uuid=True),
        ForeignKey("turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), default=ResponseKind.AGENT)
    content: Mapped[str] = mapped_column(Text)
    message_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    reply_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
