from datetime import datetime
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import BigInteger, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Hold(Base):
    __tablename__ = "holds"
    __table_args__ = (Index("ix_holds_user_live", "user_id", "expires_at"),)

    turn_id: Mapped[UUID] = mapped_column(
        SQL_UUID(as_uuid=True),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
