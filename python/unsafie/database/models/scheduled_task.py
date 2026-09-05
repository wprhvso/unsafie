from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class TaskKind(StrEnum):
    REMIND = "remind"
    TASK = "task"


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        Index("ix_scheduled_tasks_due", "enabled", "next_run_at"),
        Index("ix_scheduled_tasks_chat", "bot_id", "chat_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    origin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default=TaskKind.REMIND)
    text: Mapped[str] = mapped_column(Text)
    tz: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    interval_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def recurring(self) -> bool:
        return bool(self.cron or self.interval_sec)
