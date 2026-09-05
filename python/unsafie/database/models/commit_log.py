from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class CommitLog(Base):
    __tablename__ = "commit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    worktree_id: Mapped[int] = mapped_column(
        ForeignKey("worktrees.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    sha: Mapped[str] = mapped_column(String(40))
    previous_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
