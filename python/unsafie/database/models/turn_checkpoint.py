from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import UUID as SQL_UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class CheckpointPhase(StrEnum):
    LLM_QUERY = "llm_query"
    TOOL_EXEC = "tool_exec"
    TOOL_DONE = "tool_done"


class TurnCheckpoint(Base):
    __tablename__ = "turn_checkpoints"
    __table_args__ = (
        UniqueConstraint("turn_id", "step", "phase", name="uq_turn_checkpoints_step_phase"),
        Index("ix_turn_checkpoints_lookup", "turn_id", "step", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    turn_id: Mapped[UUID] = mapped_column(
        SQL_UUID(as_uuid=True), ForeignKey("turns.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(32))
    messages: Mapped[bytes] = mapped_column(LargeBinary)
    active_block: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    injected: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("opal_sessions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
