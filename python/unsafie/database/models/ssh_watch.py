from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class WatchMode(StrEnum):
    NOTIFY = "notify"
    TASK = "task"


class SshWatch(Base):
    __tablename__ = "ssh_watches"
    __table_args__ = (
        Index("ix_ssh_watches_due", "enabled", "next_run_at"),
        Index("ix_ssh_watches_chat", "bot_id", "chat_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    host_id: Mapped[int] = mapped_column(ForeignKey("ssh_hosts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    command: Mapped[str] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(String(255))
    interval_sec: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16), default=WatchMode.NOTIFY)
    origin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_exit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alerting: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    fails: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
