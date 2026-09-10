from datetime import datetime
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class TurnMessages(Base):
    __tablename__ = "turn_messages"

    turn_id: Mapped[UUID] = mapped_column(
        SQL_UUID(as_uuid=True), ForeignKey("turns.id", ondelete="CASCADE"), primary_key=True,
    )
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    body: Mapped[bytes] = mapped_column(LargeBinary)
    system: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
