from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class GroupMode(StrEnum):
    MENTIONS = "mentions"
    ALL = "all"
    OFF = "off"


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (UniqueConstraint("bot_id", "chat_id", name="uq_chats_bot_chat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_mode: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)
    system: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
