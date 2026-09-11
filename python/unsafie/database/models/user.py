from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base
from unsafie.database.types import EncryptedText


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    git_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    git_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_private_key: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    ssh_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    pool_max_machines: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    pool_max_background: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    pool_max_minutes_day: Mapped[int] = mapped_column(Integer, default=600, server_default="600")
    pool_max_machines_day: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    pool_priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pool_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
