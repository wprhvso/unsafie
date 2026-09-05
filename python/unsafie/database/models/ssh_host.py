from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class SshHost(Base):
    __tablename__ = "ssh_hosts"
    __table_args__ = (
        UniqueConstraint("user_id", "alias", name="uq_ssh_hosts_alias"),
        UniqueConstraint("user_id", "host", "port", "username", name="uq_ssh_hosts_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(64))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=22, server_default="22")
    username: Mapped[str] = mapped_column(String(255))
    host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def label(self) -> str:
        port = "" if self.port == 22 else f":{self.port}"
        return f"{self.username}@{self.host}{port}"
