from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Worktree(Base):
    __tablename__ = "worktrees"
    __table_args__ = (UniqueConstraint("repo_id", "branch", name="uq_worktrees_repo_branch"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(255))
    base_commit_sha: Mapped[str] = mapped_column(String(40))
    base_tree_sha: Mapped[str] = mapped_column(String(40))
    changes: Mapped[dict] = mapped_column(JSONB, default=dict)
    pending: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stash: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
