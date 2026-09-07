from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
