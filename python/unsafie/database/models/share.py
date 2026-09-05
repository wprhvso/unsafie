from datetime import datetime
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base
from unsafie.slugs import SLUG_LENGTH


class Share(Base):
    __tablename__ = "shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[UUID] = mapped_column(
        SQL_UUID(as_uuid=True), ForeignKey("responses.id", ondelete="CASCADE"), unique=True
    )
    slug: Mapped[str] = mapped_column(String(SLUG_LENGTH), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
