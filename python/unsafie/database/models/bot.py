from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True)
