from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class Repo(Base):
    __tablename__ = "repos"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repos_owner_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("installations.id", ondelete="CASCADE"), index=True
    )
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    default_branch: Mapped[str] = mapped_column(String(255))
    private: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def full(self) -> str:
        return f"{self.owner}/{self.name}"


class UserRepo(Base):
    __tablename__ = "user_repos"
    __table_args__ = (
        UniqueConstraint("user_id", "alias", name="uq_user_repos_alias"),
        UniqueConstraint("user_id", "repo_id", name="uq_user_repos_repo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(64))
