from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class JobKind(StrEnum):
    UPDATE = "update"
    SCHEDULED = "scheduled"
    WATCH = "watch"
    SYSTEM = "system"


class JobState(StrEnum):
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_ready", "state", "lane", "priority", "run_after"),
        Index("ix_jobs_dedup", "bot_id", "update_id", unique=True),
        Index("ix_jobs_chat_running", "chat_id", "state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))
    bot_id: Mapped[int] = mapped_column(Integer)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    update_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    turn_id: Mapped[UUID | None] = mapped_column(SQL_UUID(as_uuid=True), nullable=True)
    lane: Mapped[str] = mapped_column(String(32), default="stable", server_default="stable")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    resume: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    state: Mapped[str] = mapped_column(String(16), default=JobState.READY, server_default="ready")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
