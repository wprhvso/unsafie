from sqlalchemy import CheckConstraint, Float
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Config(Base):
    __tablename__ = "config"
    __table_args__ = (CheckConstraint("id = 1", name="config_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    ratio: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    oauth_ratio: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
