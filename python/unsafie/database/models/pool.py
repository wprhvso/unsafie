import uuid
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import UUID as SQL_UUID
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class MachineState(StrEnum):
    BOOTING = "booting"
    IDLE = "idle"
    LEASED = "leased"
    CI = "ci"
    GONE = "gone"


class CommandStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    LOST = "lost"
    CANCELLED = "cancelled"


class PoolDonor(Base):
    __tablename__ = "pool_donors"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(255), unique=True)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token: Mapped[str] = mapped_column(Text)
    repo: Mapped[str] = mapped_column(String(255))
    workflow: Mapped[str] = mapped_column(String(128), default="unsafie.yml")
    jobs: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    worker_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    state: Mapped[str] = mapped_column(String(32), default="new")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minutes_month: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PoolMachine(Base):
    __tablename__ = "pool_machines"
    __table_args__ = (
        Index("ix_pool_machines_state", "state", "seen_at"),
        Index("ix_pool_machines_user", "user_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    alias: Mapped[str | None] = mapped_column(String(32), nullable=True)
    donor_id: Mapped[int | None] = mapped_column(
        ForeignKey("pool_donors.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default=MachineState.IDLE)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    labels: Mapped[str] = mapped_column(String(255), default="", server_default="")
    facts: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    boot_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gone_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PoolCommand(Base):
    __tablename__ = "pool_commands"
    __table_args__ = (
        Index("ix_pool_commands_machine", "machine", "created_at"),
        Index("ix_pool_commands_user", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(SQL_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        SQL_UUID(as_uuid=True), ForeignKey("turns.id", ondelete="SET NULL"), nullable=True
    )
    command: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=CommandStatus.QUEUED)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    background: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PoolBlob(Base):
    __tablename__ = "pool_blobs"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_pool_blobs_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(512))
    size: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    sha256: Mapped[str] = mapped_column(String(64), default="", server_default="")
    machine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PoolLease(Base):
    __tablename__ = "pool_leases"
    __table_args__ = (Index("ix_pool_leases_user", "user_id", "taken_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    machine: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    turn_id: Mapped[UUID | None] = mapped_column(SQL_UUID(as_uuid=True), nullable=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commands: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class PoolUsage(Base):
    __tablename__ = "pool_usage"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_pool_usage_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    machine_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    ci_seconds: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    commands: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class PoolCiRepo(Base):
    __tablename__ = "pool_ci_repos"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_pool_ci_repos_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(255))
    label: Mapped[str] = mapped_column(String(64), default="pool")
    jobs: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    idle: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    lifetime: Mapped[int] = mapped_column(Integer, default=3600, server_default="3600")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    scale_set_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="new")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PoolCiJob(Base):
    __tablename__ = "pool_ci_jobs"
    __table_args__ = (Index("ix_pool_ci_jobs_repo", "repo_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("pool_ci_repos.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    job: Mapped[str | None] = mapped_column(String(255), nullable=True)
    machine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="assigned")
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSecret(Base):
    __tablename__ = "user_secrets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_secrets_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserKv(Base):
    __tablename__ = "user_kv"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_kv_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
