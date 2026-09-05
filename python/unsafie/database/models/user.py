from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    budget: Mapped[int] = mapped_column(BigInteger, default=-1, server_default="-1")
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    git_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
