import uuid
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text, func
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
        Index("ix_turns_root", "root_id", "created_at"),
        Index("ix_turns_user", "user_id", "created_at"),
        Index("ix_turns_alive", "status", "heartbeat_at"),
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
    root_id: Mapped[UUID] = mapped_column(SQL_UUID(as_uuid=True))
    reply_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=TurnStatus.RUNNING)
    credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("anthropic_credentials.id", ondelete="SET NULL"), nullable=True
    )
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    charge: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # Money reserved on the balance while the turn runs: spendable is balance - sum(locked).
    locked: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    num_turns: Mapped[int] = mapped_column(default=0, server_default="0")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
