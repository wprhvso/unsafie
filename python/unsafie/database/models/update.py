from datetime import datetime
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Update(Base):
    __tablename__ = "updates"
    __table_args__ = (
        UniqueConstraint("bot_id", "update_id", name="uq_updates_bot_update"),
        Index("ix_updates_message", "bot_id", "chat_id", "message_id"),
        Index("ix_updates_turn", "turn_id", "ordinal"),
        Index("ix_updates_chat_created", "bot_id", "chat_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    update_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    turn_id: Mapped[UUID | None] = mapped_column(
        SQL_UUID(as_uuid=True), ForeignKey("turns.id", ondelete="SET NULL"), nullable=True
    )
    ordinal: Mapped[int] = mapped_column(default=0, server_default="0")
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
