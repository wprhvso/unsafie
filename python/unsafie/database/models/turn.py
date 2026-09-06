import uuid
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class TurnStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        Index("ix_turns_chat", "bot_id", "chat_id", "created_at"),
        Index("ix_turns_session", "bot_id", "chat_id", "session_id", "created_at"),
        Index("ix_turns_user", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(SQL_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    parent_id: Mapped[UUID | None] = mapped_column(
        SQL_UUID(as_uuid=True),
        ForeignKey("turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reply_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    forked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), default=TurnStatus.RUNNING)
    credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("anthropic_credentials.id", ondelete="SET NULL"), nullable=True
    )
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    charge: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    num_turns: Mapped[int] = mapped_column(default=0, server_default="0")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    lane: Mapped[str] = mapped_column(String(32), default="stable", server_default="stable")
    origin: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    release_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
