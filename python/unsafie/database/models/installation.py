from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(BigInteger)
    account_login: Mapped[str] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(32))
    repository_selection: Mapped[str] = mapped_column(String(16), default="all")
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InstallationAccount(Base):
    __tablename__ = "installation_accounts"

    installation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("installations.id", ondelete="CASCADE"), primary_key=True
    )
    github_account_id: Mapped[int] = mapped_column(
        ForeignKey("github_accounts.id", ondelete="CASCADE"), primary_key=True
    )
