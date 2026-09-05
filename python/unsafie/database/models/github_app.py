from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class GithubApp(Base):
    __tablename__ = "github_app"
    __table_args__ = (CheckConstraint("id = 1", name="github_app_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    app_id: Mapped[int] = mapped_column(BigInteger)
    slug: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    html_url: Mapped[str] = mapped_column(String(512))
    client_id: Mapped[str] = mapped_column(String(64))
    client_secret: Mapped[str] = mapped_column(Text)
    webhook_secret: Mapped[str] = mapped_column(Text)
    private_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
