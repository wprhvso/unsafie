from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (
        Index("ix_transcripts_chat", "bot_id", "chat_id"),
        Index("ix_transcripts_updated", "updated_at"),
    )

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    lines: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    raw_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    body: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
